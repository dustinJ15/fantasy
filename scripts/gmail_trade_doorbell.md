# Gmail trade doorbell — setup

ESPN emails you within seconds of any trade proposal. A tiny Google Apps Script watches your Gmail
for those emails and fires the "FF trade offer" routine, which re-reads ESPN and emails you a verdict.
This is the primary alert path. The hourly GitHub poller (`.github/workflows/trade-poll.yml`) is the
backstop, and the morning briefing is the final net.

Nothing in the script is secret; the two secrets live only in Script Properties inside your Google account.

## What you need first
- The routine's **trigger id** and **API fire token**. Open the "FF trade offer" routine page (URL in
  `ops.local.md`) and copy both from its API trigger section.

## 1. Create the project
1. Go to https://script.google.com while signed in to the Gmail account ESPN emails.
2. Click **New project**. Rename it (top-left, "Untitled project") to `FF trade doorbell`.
3. In the editor, delete the placeholder `myFunction` and paste the whole contents of
   `scripts/gmail_trade_doorbell.gs`. Press **Ctrl+S** to save.

## 2. Set the two Script Properties
1. Click the gear icon (**Project Settings**) in the left sidebar.
2. Scroll to **Script Properties** and click **Add script property**. Add:
   - `FF_TRADE_ROUTINE_ID` = the trigger id
   - `FF_ROUTINE_FIRE_TOKEN` = the fire token
3. Click **Save script properties**.

## 3. Authorize once by running it by hand
1. Back in the editor (the `< >` icon), pick `checkForTradeOffers` in the function dropdown next to
   **Run**, then click **Run**.
2. A dialog asks for permission. Click **Review permissions**, choose your account, click **Advanced**,
   then **Go to FF trade doorbell (unsafe)** (it is unsafe only in the sense that Google did not review
   it; you wrote it), then **Allow**. It needs Gmail access (to search and label) and "connect to an
   external service" (to call the fire endpoint).
3. The run finishes. If there is no unhandled ESPN proposal email in the last 2 hours, it does nothing,
   which is fine.

## 4. Add the 1-minute trigger
1. Click the clock icon (**Triggers**) in the left sidebar, then **Add Trigger** (bottom right).
2. Set: function `checkForTradeOffers`, deployment `Head`, event source **Time-driven**,
   type **Minutes timer**, interval **Every minute**. Failure notifications: **Notify me daily**.
3. Click **Save**.

From now on, each ESPN proposal email gets the label `ff-alerted` after the routine is fired, and you
should get an `FF trade offer — <league> — <date>` email a few minutes later.

## Debugging
- **Execution log:** click the list icon (**Executions**) in the left sidebar. Each run shows its
  status and any `console.log` lines: "Fired routine for ...", "Fire endpoint returned HTTP ...", or
  "Missing Script Property ...".
- **Nothing fires:** confirm both Script Properties are still set (Project Settings), that the
  trigger still exists (Triggers), and that the ESPN email is in the inbox from `fantasy@espnmail.com`
  with "Trade Proposal" in the subject. Remove the `ff-alerted` label from the email to make the script
  retry it.
- **HTTP 401/403 in the log:** the fire token was rotated. Copy the new one from the routine page into
  the Script Property.
- **HTTP 404:** the trigger id is wrong or the routine was deleted.
- **Rotating the token:** only the Script Property changes; the script file never does.
