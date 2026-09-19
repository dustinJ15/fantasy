// Stubbed Apps Script runtime for scripts/gmail_trade_doorbell.gs.
//
// The doorbell runs in Google's environment, so pytest cannot reach it and a mistake there is only
// visible as a trade offer that never gets announced. This fakes GmailApp/UrlFetchApp/Properties and
// asserts the failure paths: transient faults retry, a rejected fire escalates, and no proposal is
// ever announced twice. Run from the repo root, after editing the .gs and before pasting it in:
//
//   node scripts/gmail_trade_doorbell.test.js
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync('scripts/gmail_trade_doorbell.gs', 'utf8');

let out = [], fails = 0;
const eq = (label, a, b) => { const ok = JSON.stringify(a) === JSON.stringify(b);
  if (!ok) { fails++; console.log(`  FAIL ${label}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`); }
  else console.log(`  ok   ${label}`); };

function makeEnv({searchFails = 0, fireCodes = [200], labelFails = 0, msgId = 'm1'} = {}) {
  const state = { props: {FF_TRADE_ROUTINE_ID: 'trig_x', FF_ROUTINE_FIRE_TOKEN: 'tok'},
                  fires: 0, labels: 0, mails: [], slept: 0, searches: 0 };
  let sf = searchFails, lf = labelFails, fi = 0;
  const msg = { getId: () => msgId, getSubject: () => 'A Trade Proposal in Your ESPN Fantasy Football League',
                getFrom: () => 'ESPN <fantasy@espnmail.com>', getDate: () => new Date('2026-09-20T00:00:00Z') };
  const thread = { getMessages: () => [msg],
                   addLabel: () => { if (lf-- > 0) throw new Error('label backend error'); state.labels++; } };
  const ctx = {
    console, Date, Math, JSON, Array, String, parseInt, Error,
    GmailApp: { search: () => { state.searches++; if (sf-- > 0) throw new Error('We\'re sorry, a server error occurred.'); return [thread]; },
                getUserLabelByName: () => ({name: 'ff-alerted'}), createLabel: () => ({name: 'ff-alerted'}) },
    PropertiesService: { getScriptProperties: () => ({
      getProperty: k => (k in state.props ? state.props[k] : null),
      setProperty: (k, v) => { state.props[k] = v; },
      deleteProperty: k => { delete state.props[k]; } }) },
    UrlFetchApp: { fetch: () => { state.fires++; const c = fireCodes[Math.min(fi++, fireCodes.length - 1)];
      return { getResponseCode: () => c, getContentText: () => 'body' }; } },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    Utilities: { sleep: ms => { state.slept += ms; } },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'dbj2297@gmail.com' }) },
    MailApp: { sendEmail: (to, subj, body) => state.mails.push({to, subj}) },
  };
  vm.createContext(ctx); vm.runInContext(src, ctx);
  return { ctx, state };
}

console.log('transient search error is retried, run succeeds, no alarm raised');
{ const {ctx, state} = makeEnv({searchFails: 2});
  ctx.checkForTradeOffers();
  eq('searched 3 times', state.searches, 3);
  eq('fired once', state.fires, 1);
  eq('labeled', state.labels, 1);
  eq('no failed-run counter left', state.props.ff_failed_runs, undefined);
  eq('backed off', state.slept, 3000); }

console.log('search down all attempts: run stays quiet until the 5th consecutive failure');
{ const {ctx, state} = makeEnv({searchFails: 99});
  for (let i = 1; i <= 4; i++) ctx.checkForTradeOffers();  // must not throw
  eq('4 failures recorded', state.props.ff_failed_runs, '4');
  let threw = false;
  try { ctx.checkForTradeOffers(); } catch (e) { threw = true; }
  eq('5th failure surfaces to Apps Script', threw, true); }

console.log('fire rejected with 401: no label, no duplicate, email after 3 tries');
{ const {ctx, state} = makeEnv({fireCodes: [401]});
  ctx.checkForTradeOffers(); ctx.checkForTradeOffers();
  eq('no email yet', state.mails.length, 0);
  eq('never labeled', state.labels, 0);
  ctx.checkForTradeOffers();
  eq('emailed on 3rd', state.mails.length, 1);
  eq('email subject', state.mails[0].subj, 'FF trade doorbell — cannot reach the trade routine');
  ctx.checkForTradeOffers();
  eq('cooldown holds the 4th', state.mails.length, 1);
  eq('401 not retried within a run', state.fires, 4); }

console.log('fire 500 is retried inside the run');
{ const {ctx, state} = makeEnv({fireCodes: [500, 500, 200]});
  ctx.checkForTradeOffers();
  eq('three attempts', state.fires, 3);
  eq('labeled after success', state.labels, 1); }

console.log('label write fails after a successful fire: next run repairs, does not re-fire');
{ const {ctx, state} = makeEnv({labelFails: 3});   // exhausts the label retries
  ctx.checkForTradeOffers();
  eq('fired once', state.fires, 1);
  eq('not labeled', state.labels, 0);
  eq('id remembered', JSON.parse(state.props.ff_fired_message_ids), ['m1']);
  ctx.checkForTradeOffers();
  eq('still fired only once', state.fires, 1);
  eq('label repaired', state.labels, 1); }

console.log('missing Script Properties: quiet no-op, nothing fired');
{ const {ctx, state} = makeEnv();
  delete state.props.FF_ROUTINE_FIRE_TOKEN;
  ctx.checkForTradeOffers();
  eq('no fire', state.fires, 0);
  eq('no failure recorded', state.props.ff_failed_runs, undefined); }

console.log(fails === 0 ? '\nALL PASS' : `\n${fails} FAILING`);
process.exit(fails === 0 ? 0 : 1);
