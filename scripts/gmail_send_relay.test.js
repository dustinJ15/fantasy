// Stubbed Apps Script runtime for scripts/gmail_send_relay.gs.
//
// The relay runs in Google's environment, so pytest cannot reach it and a mistake there is only visible
// as a briefing that fell back to the connector paste. This fakes GmailApp/PropertiesService/Session/
// ContentService and asserts the contract `ff email` (src/ff/mail.py) relies on: a good request sends
// exactly once with the html and markdown as given, a bad token is a 403, a missing field or a non-JSON
// body is a 400, a recipient outside the allowlist is a 403, and nothing is sent on any refusal.
// Run from the repo root, after editing the .gs and before pasting it in:
//
//   node scripts/gmail_send_relay.test.js
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync('scripts/gmail_send_relay.gs', 'utf8');

let fails = 0;
const eq = (label, a, b) => { const ok = JSON.stringify(a) === JSON.stringify(b);
  if (!ok) { fails++; console.log(`  FAIL ${label}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`); }
  else console.log(`  ok   ${label}`); };

const HTML = '<html><body>\n<p>Hold Hubbard</p>\n<p>ünïcode · μ 17.8</p>\n</body></html>\n';
const MARKDOWN = '# Week 7\n\n- Hold Hubbard\n';
const GOOD = { token: 'tok-1', subject: 'FF briefing — Week 7 — 2026-10-20', to: 'dustin@example.com',
               markdown: MARKDOWN, html: HTML };

function makeEnv({ props = { FF_MAIL_RELAY_TOKEN: 'tok-1' }, sendFails = false } = {}) {
  const state = { props: { ...props }, sent: [], sendFails };
  const ctx = {
    console, JSON, Array, Object, String, Math, Error,
    PropertiesService: { getScriptProperties: () => ({
      getProperty: k => (k in state.props ? state.props[k] : null),
      setProperty: (k, v) => { state.props[k] = v; },
      deleteProperty: k => { delete state.props[k]; } }) },
    GmailApp: { sendEmail: (to, subject, body, options) => {
      if (state.sendFails) throw new Error('Service invoked too many times');
      state.sent.push({ to, subject, body, options }); } },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'dustin@example.com' }) },
    ContentService: { MimeType: { JSON: 'application/json' },
      createTextOutput: text => { const out = { text, mime: null, setMimeType(m) { out.mime = m; return out; } }; return out; } },
  };
  vm.createContext(ctx); vm.runInContext(src, ctx);
  const post = body => {
    const out = ctx.doPost({ postData: { contents: typeof body === 'string' ? body : JSON.stringify(body) } });
    return { verdict: JSON.parse(out.text), mime: out.mime };
  };
  return { ctx, state, post };
}

console.log('a good request sends exactly once, html and markdown as given');
{ const { state, post } = makeEnv();
  const { verdict, mime } = post(GOOD);
  eq('code 200', verdict.code, 200);
  eq('ok', verdict.ok, true);
  eq('json response', mime, 'application/json');
  eq('one send', state.sent.length, 1);
  eq('recipient', state.sent[0].to, 'dustin@example.com');
  eq('subject', state.sent[0].subject, GOOD.subject);
  eq('plain part is the markdown byte for byte', state.sent[0].body, MARKDOWN);
  eq('rich part is the html byte for byte', state.sent[0].options.htmlBody, HTML); }

console.log('a bad token is a 403 and sends nothing');
{ const { state, post } = makeEnv();
  const { verdict } = post({ ...GOOD, token: 'tok-2' });
  eq('code 403', verdict.code, 403);
  eq('ok false', verdict.ok, false);
  eq('nothing sent', state.sent.length, 0); }

console.log('no token on record means nobody is authorized (403), not everybody');
{ const { state, post } = makeEnv({ props: {} });
  const { verdict } = post(GOOD);
  eq('code 403', verdict.code, 403);
  eq('nothing sent', state.sent.length, 0); }

console.log('a missing field is a 400 and sends nothing, whatever the token');
{ const { state, post } = makeEnv();
  for (const field of ['subject', 'to', 'markdown', 'html', 'token']) {
    const body = { ...GOOD }; delete body[field];
    const { verdict } = post(body);
    eq(`missing ${field}: 400`, verdict.code, 400);
    eq(`missing ${field}: names it`, verdict.detail.includes(field), true);
  }
  const { verdict } = post({ ...GOOD, html: '' });
  eq('empty html: 400', verdict.code, 400);
  eq('nothing sent', state.sent.length, 0); }

console.log('a body that is not JSON, or not an object, is a 400');
{ const { state, post } = makeEnv();
  eq('garbage', post('not json').verdict.code, 400);
  eq('array', post([1, 2]).verdict.code, 400);
  eq('no body at all', JSON.parse(makeEnv().ctx.doPost({}).text).code, 400);
  eq('nothing sent', state.sent.length, 0); }

console.log('a recipient outside the allowlist is a 403; the account itself and FF_MAIL_RELAY_TO are inside it');
{ const { state, post } = makeEnv();
  eq('a stranger', post({ ...GOOD, to: 'stranger@example.com' }).verdict.code, 403);
  eq('nothing sent', state.sent.length, 0);
  eq('the account itself, any case', post({ ...GOOD, to: 'Dustin@Example.com' }).verdict.code, 200);
  state.props.FF_MAIL_RELAY_TO = 'other@example.com, third@example.com';
  eq('an allowlisted address', post({ ...GOOD, to: 'third@example.com' }).verdict.code, 200);
  eq('still not a stranger', post({ ...GOOD, to: 'stranger@example.com' }).verdict.code, 403);
  eq('two sends in all', state.sent.length, 2); }

console.log('GmailApp refusing the send is a 500 with the reason, not a silent 200');
{ const { state, post } = makeEnv({ sendFails: true });
  const { verdict } = post(GOOD);
  eq('code 500', verdict.code, 500);
  eq('ok false', verdict.ok, false);
  eq('reason in detail', verdict.detail.includes('too many times'), true);
  eq('nothing recorded as sent', state.sent.length, 0); }

console.log('a GET is a status line, never a send');
{ const { ctx, state } = makeEnv();
  const out = JSON.parse(ctx.doGet().text);
  eq('ok', out.ok, true);
  eq('nothing sent', state.sent.length, 0); }

console.log('sendTestEmail sends one email to the account itself through the same path');
{ const { ctx, state } = makeEnv();
  ctx.sendTestEmail();
  eq('one send', state.sent.length, 1);
  eq('to self', state.sent[0].to, 'dustin@example.com');
  eq('html part present', state.sent[0].options.htmlBody.includes('<html>'), true); }

console.log(fails === 0 ? '\nALL PASS' : `\n${fails} FAILING`);
process.exit(fails === 0 ? 0 : 1);
