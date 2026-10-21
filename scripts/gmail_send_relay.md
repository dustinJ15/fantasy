# Gmail send relay — setup

`ff email` sends the morning briefing and the trade-offer alert. The cloud container it runs in leaves through a web
proxy that carries HTTP and HTTPS only, so Gmail SMTP (port 465) hangs there until it times out and the skill fell
back to pasting the email into the Gmail connector every morning (2026-10-21). This relay is the path the proxy can
reach: a tiny Google Apps Script web app in your account that takes an HTTPS POST of the rendered files and sends
them from your Gmail with `GmailApp`. The body on the wire is exactly what `ff` rendered.

The script is `scripts/gmail_send_relay.gs`, next to the trade doorbell. Nothing in it is secret; the token lives in a
Script Property inside your Google account and in the cloud environment, nowhere in the repo.

## What you need first
- A token: any long random string. `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` makes one.
- The recipient address the briefing goes to (`BRIEFING_TO` in the cloud env). The relay sends only to the Gmail
  account's own address unless you allow more (step 2).

## 1. Create the project
1. Go to https://script.google.com while signed in to the Gmail account the briefing should come from.
2. Click **New project**. Rename it (top-left, "Untitled project") to `FF mail relay`.
3. In the editor, delete the placeholder `myFunction` and paste the whole contents of `scripts/gmail_send_relay.gs`.
   Press **Ctrl+S** to save.

## 2. Set the Script Property
1. Click the gear icon (**Project Settings**) in the left sidebar.
2. Scroll to **Script Properties** and click **Add script property**. Add:
   - `FF_MAIL_RELAY_TOKEN` = the token
   - `FF_MAIL_RELAY_TO` = extra allowed recipients, comma-separated (optional; the account's own address is always
     allowed). Set it when `BRIEFING_TO` is not the Gmail account itself.
3. Click **Save script properties**.

## 3. Authorize once by running it by hand
1. Back in the editor (the `< >` icon), pick `sendTestEmail` in the function dropdown next to **Run**, then click **Run**.
2. A dialog asks for permission. Click **Review permissions**, choose your account, click **Advanced**, then
   **Go to FF mail relay (unsafe)** (unsafe only in the sense that Google did not review it; you wrote it), then
   **Allow**. It needs permission to send email as you.
3. The log says `Sent: sent "FF mail relay — test" to <you>` and the test email is in your inbox.

## 4. Deploy it as a web app
1. Click **Deploy** (top right) > **New deployment**. Click the gear next to "Select type" and choose **Web app**.
2. Set: description `ff email`, **Execute as: Me**, **Who has access: Anyone**. "Anyone" is what lets `ff` call it
   without a Google login; the token and the recipient allowlist are what keep it yours.
3. Click **Deploy**, then copy the **Web app URL**. It ends in `/exec`. That is `FF_MAIL_RELAY_URL`.
4. Check it from a shell (the `-L` matters: Apps Script answers with a redirect first):
   ```
   curl -sL "<the /exec URL>"
   ```
   prints `{"ok":true,"code":200,"detail":"ff mail relay: POST ..."}`. A sign-in page instead means the deployment is
   not "Anyone", or the URL is the editor's `/dev` URL.

## 5. Tell `ff` about it
Add both to the cloud environment `fantasy` (Claude Code > environments; the same box that holds `ESPN_S2`) and to
your local `.env`:
```
FF_MAIL_RELAY_URL=<the /exec URL>
FF_MAIL_RELAY_TOKEN=<the token>
```
`uv run ff doctor` then prints `email: HTTPS relay (FF_MAIL_RELAY_URL, Apps Script) to <BRIEFING_TO> (ff email)`, and
`uv run ff email <file> --subject "test"` sends it. When both the relay and `GMAIL_USER`/`GMAIL_APP_PASSWORD` are set
the relay is used; SMTP is the path only when the relay variables are absent (it works from a laptop, never from the
cloud container). `GMAIL_USER`/`GMAIL_APP_PASSWORD` can be removed from the cloud env once the relay sends.

## How it answers
Apps Script gives every web-app response HTTP 200, so the relay's verdict is the `code` in its JSON body:
`{"ok":true,"code":200}` sent; `400` a missing field or a body that is not JSON; `403` a bad token or a recipient
outside the allowlist; `500` `GmailApp.sendEmail` refused (the daily quota, 100 recipients a day on a consumer
account, is the usual reason). `ff email` exits non-zero with that detail on anything but a 200, and the skill falls
back to the Gmail connector paste. One request is one send; nothing is retried in the script.

## Debugging
- **Execution log:** the list icon (**Executions**) in the left sidebar shows each POST and any error.
- **`ff email` says "mail relay refused the send (403): bad token":** the Script Property and `FF_MAIL_RELAY_TOKEN` in
  the cloud env differ. Set one to the other; nothing else changes.
- **"recipient not allowed":** `BRIEFING_TO` is not the Gmail account and not in `FF_MAIL_RELAY_TO`.
- **"answered with something other than its JSON verdict":** the URL is wrong (`/dev`, or an old deployment that was
  archived), or access is not "Anyone". Re-check step 4.
- **"mail relay unreachable":** the proxy or Google is down; `curl -sL` the URL from the same place. The skill's
  connector fallback covers the morning.
- **After editing the script:** run `node scripts/gmail_send_relay.test.js` in the repo first (it exercises the
  token, field, recipient and one-send rules against a stubbed Apps Script runtime). Then paste the new contents in
  and, because the `/exec` URL keeps serving the version it was deployed with, **Deploy > Manage deployments >
  edit (pencil) > Version: New version > Deploy**. The URL does not change.
- **Rotating the token:** change the Script Property and the cloud env var; the script and the URL stay.
