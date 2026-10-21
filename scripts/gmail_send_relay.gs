/**
 * Gmail send relay for the morning briefing (TODO C7).
 *
 * The cloud container that runs `ff` leaves through a web proxy that carries HTTP and HTTPS only, so
 * `ff email` over SMTP (smtp.gmail.com:465) hangs there until it times out. This web app is the path the
 * proxy can reach: `ff email` POSTs the rendered files here and this script sends them from your Gmail
 * with GmailApp. The body on the wire is exactly what `ff` rendered; nothing is assembled by hand.
 *
 * Request: POST JSON {token, subject, to, markdown, html}. Every field is required. `markdown` is the
 * plain part, `html` the rich part, `to` the recipient.
 * Response: JSON {ok, code, detail}. Apps Script answers every web-app request with HTTP 200 (and a
 * redirect first), so the relay's own verdict is the `code` field: 200 sent, 400 a missing field or a body
 * that is not JSON, 403 a bad token or a recipient outside the allowlist, 500 GmailApp refused the send.
 *
 * Who may send: the token in the body must equal the Script Property FF_MAIL_RELAY_TOKEN. Who may receive:
 * the account's own address, plus any address in the Script Property FF_MAIL_RELAY_TO (comma-separated,
 * optional). A leaked token therefore sends mail from your account only to you.
 *
 * One send per request: a request that validates sends exactly once, and nothing is retried here; `ff
 * email` reports the relay's verdict and the skill falls back to the Gmail connector paste on a failure.
 *
 * No secrets live in this file. Set the Script Property (Project Settings > Script Properties):
 *   FF_MAIL_RELAY_TOKEN   a long random string; the same value is FF_MAIL_RELAY_TOKEN in the cloud env
 *   FF_MAIL_RELAY_TO      optional, extra allowed recipients
 * Setup steps: scripts/gmail_send_relay.md
 */

var PROP_TOKEN = 'FF_MAIL_RELAY_TOKEN';
var PROP_ALLOWED_TO = 'FF_MAIL_RELAY_TO';
var REQUIRED_FIELDS = ['token', 'subject', 'to', 'markdown', 'html'];

/** The web app's POST entry point. */
function doPost(e) {
  return respond_(handlePost_(e));
}

/** A GET answers with a status line, so the deployment URL can be checked in a browser or with curl. */
function doGet() {
  return respond_({ ok: true, code: 200, detail: 'ff mail relay: POST {token, subject, to, markdown, html}' });
}

/** Validates the request and sends once. Returns the verdict {ok, code, detail}. */
function handlePost_(e) {
  var body = parseBody_(e);
  if (!body) {
    return { ok: false, code: 400, detail: 'body is not a JSON object' };
  }
  var missing = REQUIRED_FIELDS.filter(function (field) {
    return typeof body[field] !== 'string' || body[field] === '';
  });
  if (missing.length > 0) {
    return { ok: false, code: 400, detail: 'missing field(s): ' + missing.join(', ') };
  }

  var props = PropertiesService.getScriptProperties();
  var expected = props.getProperty(PROP_TOKEN);
  if (!expected) {
    // No token on record means nobody is authorized, not that everybody is.
    return { ok: false, code: 403, detail: 'Script Property ' + PROP_TOKEN + ' is not set' };
  }
  if (!sameString_(body.token, expected)) {
    return { ok: false, code: 403, detail: 'bad token' };
  }

  var to = body.to.trim();
  if (!recipientAllowed_(to, props)) {
    return { ok: false, code: 403, detail: 'recipient not allowed: ' + to };
  }

  try {
    GmailApp.sendEmail(to, body.subject, body.markdown, { htmlBody: body.html });
  } catch (err) {
    return { ok: false, code: 500, detail: 'GmailApp.sendEmail failed: ' + err };
  }
  return { ok: true, code: 200, detail: 'sent "' + body.subject + '" to ' + to };
}

/** The POST body as an object, or null when it is absent, not JSON, or not an object. */
function parseBody_(e) {
  var raw = e && e.postData && e.postData.contents;
  if (!raw) {
    return null;
  }
  var parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return null;
  }
  return parsed;
}

/** The account's own address, plus FF_MAIL_RELAY_TO (comma-separated), compared case-insensitively. */
function recipientAllowed_(to, props) {
  var allowed = [];
  var own = Session.getEffectiveUser().getEmail();
  if (own) {
    allowed.push(own);
  }
  var extra = props.getProperty(PROP_ALLOWED_TO) || '';
  extra.split(',').forEach(function (address) {
    if (address.trim()) {
      allowed.push(address.trim());
    }
  });
  var wanted = to.toLowerCase();
  return allowed.some(function (address) {
    return address.toLowerCase() === wanted;
  });
}

/** Constant-time string comparison, so a token cannot be guessed a character at a time by timing. */
function sameString_(a, b) {
  a = String(a);
  b = String(b);
  var diff = a.length ^ b.length;
  var n = Math.max(a.length, b.length);
  for (var i = 0; i < n; i++) {
    diff |= (a.charCodeAt(i % a.length) || 0) ^ (b.charCodeAt(i % b.length) || 0);
  }
  return diff === 0;
}

function respond_(verdict) {
  return ContentService.createTextOutput(JSON.stringify(verdict)).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Run by hand from the editor after setup: sends a one-line test email to yourself through the same path
 * `ff email` uses, so a wrong Script Property or a missing Gmail authorization shows here, not at 6 AM.
 */
function sendTestEmail() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty(PROP_TOKEN);
  if (!token) {
    console.log('Missing Script Property ' + PROP_TOKEN + '.');
    return;
  }
  var own = Session.getEffectiveUser().getEmail();
  var verdict = handlePost_({
    postData: {
      contents: JSON.stringify({
        token: token,
        subject: 'FF mail relay — test',
        to: own,
        markdown: 'The relay works. ff email will send the briefing this way.\n',
        html: '<html><body><p>The relay works. <code>ff email</code> will send the briefing this way.</p></body></html>\n',
      }),
    },
  });
  console.log(verdict.ok ? 'Sent: ' + verdict.detail : 'FAILED (' + verdict.code + '): ' + verdict.detail);
}
