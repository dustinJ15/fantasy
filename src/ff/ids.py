"""Player ID crosswalk: espn_id <-> gsis_id <-> sleeper_id <-> fantasypros_id, with name fallback."""
from __future__ import annotations

import re
import unicodedata

import polars as pl

from .sources import fantasypros, sleeper

def _int(x) -> int:
    return int(float(x))


SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.I)


def norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = SUFFIX.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


class Crosswalk:
    def __init__(self):
        ids = fantasypros.player_ids()
        self.df = ids
        self.by_espn: dict[str, dict] = {}
        self.by_name: dict[str, dict] = {}
        for r in ids.select(["espn_id", "gsis_id", "sleeper_id", "fantasypros_id", "name", "merge_name", "position", "team"]).iter_rows(named=True):
            r = {k: (None if v in ("NA", "") else v) for k, v in r.items()}
            if r["espn_id"] is not None:
                self.by_espn[str(_int(r["espn_id"]))] = r
            key = (norm_name(r["name"]), r["position"])
            self.by_name.setdefault(key, r)
        # Sleeper fills gaps (rookies missing from the FP db)
        for sid, p in sleeper.players().items():
            eid = p.get("espn_id")
            if eid and str(eid) not in self.by_espn:
                self.by_espn[str(eid)] = {"espn_id": eid, "gsis_id": p.get("gsis_id"), "sleeper_id": sid,
                                          "fantasypros_id": p.get("fantasy_data_id"), "name": p.get("full_name"),
                                          "position": p.get("position"), "team": p.get("team")}
        self.unmatched: list[str] = []

    def sleeper_id(self, espn_id: int | str, name: str = "", pos: str = "") -> str | None:
        r = self.lookup(espn_id, name, pos)
        sid = r.get("sleeper_id") if r else None
        return str(_int(sid)) if sid not in (None, "NA", "") else None

    def lookup(self, espn_id: int | str, name: str = "", pos: str = "") -> dict | None:
        r = self.by_espn.get(str(espn_id))
        if r:
            return r
        pos_key = "DST" if pos == "D/ST" else pos
        r = self.by_name.get((norm_name(name), pos_key))
        if not r and pos != "D/ST":
            self.unmatched.append(f"{name} ({pos}, espn {espn_id})")
        return r

    def fp_weekly_index(self) -> dict[str, dict]:
        """fantasypros_id -> fp weekly row, plus ('name',pos) fallback keys."""
        ecr = fantasypros.weekly_ecr()
        out = {}
        for r in ecr.iter_rows(named=True):
            if r.get("fantasypros_id") not in (None, "NA"):
                out[str(_int(r["fantasypros_id"]))] = r
            pos = r.get("pos") or ""
            out[f"name:{norm_name(r.get('player_name'))}:{pos}"] = r
        return out

    def fp_row(self, fp_index: dict, espn_id: int, name: str, pos: str) -> dict | None:
        x = self.lookup(espn_id, name, pos)
        if x and x.get("fantasypros_id") not in (None, "NA"):
            r = fp_index.get(str(_int(x["fantasypros_id"])))
            if r:
                return r
        pos_key = "DST" if pos == "D/ST" else pos
        r = fp_index.get(f"name:{norm_name(name)}:{pos_key}")
        if r:
            return r
        # D/ST names differ ("Eagles D/ST" vs "Philadelphia Eagles"); match on team
        if pos == "D/ST":
            for k, v in fp_index.items():
                if k.startswith("name:") and v.get("pos") == "DST" and name.split(" ")[0].lower() in (v.get("player_name") or "").lower():
                    return v
        return None
