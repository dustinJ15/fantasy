/**
 * Gmail doorbell for ESPN trade proposals.
 *
 * ESPN emails "A Trade Proposal in Your ESPN Fantasy Football League" within seconds of a proposal.
 * This script runs every minute, finds such emails that have not been handled yet, and fires the
 * "FF trade offer" routine. The routine re-reads ESPN itself, so the payload is only a doorbell.
 *
 * Three things keep a bad minute from costing an alert:
 *   - transient Google faults are retried, and a single failed run stays quiet (the next minute
 *     re-runs anyway); only a sustained outage is allowed to raise Apps Script's failure notice
 *   - a message id is recorded as fired *before* the thread is labeled, so a failed label write
 *     cannot cause a second alert for the same proposal
 *   - a fire that keeps being rejected (rotated token, deleted routine) emails you directly,
 *     because nobody reads an Executions log
 *
 * No secrets live in this file. Set two Script Properties (Project Settings > Script Properties):
 *   FF_TRADE_ROUTINE_ID   the routine's trigger id
 *   FF_ROUTINE_FIRE_TOKEN the routine's API fire token
 * Setup steps: scripts/gmail_trade_doorbell.md
 */

var LABEL_NAME = 'ff-alerted';
var MAX_THREADS = 5;
var SEARCH =
  'from:fantasy@espnmail.com subject:"Trade Proposal" newer_than:2h -label:' + LABEL_NAME;

// Retries for transient Google faults ("a server error occurred", Gmail backend hiccups).
var RETRY_ATTEMPTS = 3;
var RETRY_BASE_MS = 1000;

// A run that throws is normally swallowed: the trigger fires again in a minute. Only this many
// consecutive failures means something is actually wrong, and Apps Script should say so.
var FAILED_RUNS_BEFORE_ALARM = 5;

// A fire rejected this many times in a row emails you, at most once per cooldown.
var FIRE_FAILURES_BEFORE_EMAIL = 3;
var ESCALATION_COOLDOWN_MS = 60 * 60 * 1000;

// Message ids already fired, kept so a failed label write cannot double-alert.
var FIRED_IDS_KEPT = 50;

var PROP_FAILED_RUNS = 'ff_failed_runs';
var PROP_FIRE_FAILURES = 'ff_fire_failures';
var PROP_LAST_ESCALATION = 'ff_last_escalation_ms';
var PROP_FIRED_IDS = 'ff_fired_message_ids';

function checkForTradeOffers() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    // A previous minute is still working. Nothing is lost; it holds the same search.
    console.log('Another run is in progress; skipping this minute.');
    return;
  }
  try {
    checkOnce_();
    recordRunOutcome_(true);
  } catch (err) {
    var inARow = recordRunOutcome_(false);
    console.log('Run failed (' + inARow + ' in a row): ' + err);
    if (inARow >= FAILED_RUNS_BEFORE_ALARM) {
      // Sustained failure: let it surface as an Apps Script failure notification.
      throw err;
    }
  } finally {
    lock.releaseLock();
  }
}

function checkOnce_() {
  var props = PropertiesService.getScriptProperties();
  var routineId = props.getProperty('FF_TRADE_ROUTINE_ID');
  var token = props.getProperty('FF_ROUTINE_FIRE_TOKEN');
  if (!routineId || !token) {
    console.log('Missing Script Property FF_TRADE_ROUTINE_ID or FF_ROUTINE_FIRE_TOKEN; doing nothing.');
    return;
  }

  var threads = withRetry_('Gmail search', function () {
    return GmailApp.search(SEARCH, 0, MAX_THREADS);
  });
  if (threads.length === 0) {
    return;
  }
  var label = withRetry_('label lookup', function () {
    return getOrCreateLabel_(LABEL_NAME);
  });

  threads.forEach(function (thread) {
    try {
      handleThread_(thread, label, props, routineId, token);
    } catch (err) {
      // One bad thread must not cost the others their alert; the search finds it again next minute.
      console.log('Thread failed: ' + err + '; will retry next run.');
    }
  });
}

function handleThread_(thread, label, props, routineId, token) {
  var messages = thread.getMessages().filter(function (m) {
    return isProposal_(m);
  });
  if (messages.length === 0) {
    // Thread matched on an older message; nothing new to announce.
    withRetry_('label write', function () {
      thread.addLabel(label);
      return true;
    });
    return;
  }
  var msg = messages[messages.length - 1];
  var messageId = msg.getId();
  var subject = msg.getSubject();
  var date = msg.getDate().toISOString();

  if (alreadyFired_(props, messageId)) {
    // Fired on an earlier run; only the label write was left undone.
    withRetry_('label write', function () {
      thread.addLabel(label);
      return true;
    });
    console.log('Already fired for "' + subject + '" (' + date + '); label repaired.');
    return;
  }

  var result = fireRoutine_(routineId, token, subject, date);
  if (!result.ok) {
    var inARow = recordFireOutcome_(props, false);
    console.log('Fire failed (' + inARow + ' in a row) for "' + subject + '": ' + result.detail);
    maybeEscalate_(props, inARow, subject, result.detail);
    return; // No label, so the next run tries this proposal again.
  }
  recordFireOutcome_(props, true);
  // Recorded before the label write: if labeling throws, the next run repairs the label
  // instead of firing a second alert for the same proposal.
  rememberFiredId_(props, messageId);
  withRetry_('label write', function () {
    thread.addLabel(label);
    return true;
  });
  console.log('Fired routine for "' + subject + '" (' + date + '); labeled ' + LABEL_NAME + '.');
}

function isProposal_(message) {
  var from = (message.getFrom() || '').toLowerCase();
  var subject = message.getSubject() || '';
  return from.indexOf('fantasy@espnmail.com') !== -1 && subject.indexOf('Trade Proposal') !== -1;
}

/**
 * Fires the routine. Returns {ok: boolean, detail: string}. Retries transport errors and 5xx;
 * a 4xx is a real answer (bad token, wrong id) and is returned immediately.
 */
function fireRoutine_(routineId, token, subject, date) {
  var url = 'https://api.anthropic.com/v1/claude_code/routines/' + encodeURIComponent(routineId) + '/fire';
  var body = {
    text: 'ESPN emailed a new trade proposal (' + subject + ', ' + date + '). Re-read ESPN and evaluate.',
  };
  var options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      'anthropic-beta': 'experimental-cc-routine-2026-04-01',
      'anthropic-version': '2023-06-01',
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  };

  var lastDetail = '';
  for (var attempt = 0; attempt < RETRY_ATTEMPTS; attempt++) {
    if (attempt > 0) {
      Utilities.sleep(RETRY_BASE_MS * Math.pow(2, attempt - 1));
    }
    var code;
    try {
      var response = UrlFetchApp.fetch(url, options);
      code = response.getResponseCode();
      if (code >= 200 && code < 300) {
        return { ok: true, detail: 'HTTP ' + code };
      }
      lastDetail = 'HTTP ' + code + ': ' + String(response.getContentText()).slice(0, 500);
    } catch (err) {
      lastDetail = 'request threw: ' + err;
      continue; // Transport failure; worth another attempt.
    }
    if (code < 500) {
      return { ok: false, detail: lastDetail }; // 401/404 will not fix themselves.
    }
  }
  return { ok: false, detail: lastDetail };
}

/** Runs fn, retrying transient Google faults with backoff. Throws the last error if all fail. */
function withRetry_(what, fn) {
  var lastErr;
  for (var attempt = 0; attempt < RETRY_ATTEMPTS; attempt++) {
    if (attempt > 0) {
      Utilities.sleep(RETRY_BASE_MS * Math.pow(2, attempt - 1));
    }
    try {
      return fn();
    } catch (err) {
      lastErr = err;
      console.log(what + ' attempt ' + (attempt + 1) + ' failed: ' + err);
    }
  }
  throw lastErr;
}

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

/** Returns how many runs have now failed in a row (0 after a success). */
function recordRunOutcome_(ok) {
  return bumpCounter_(PropertiesService.getScriptProperties(), PROP_FAILED_RUNS, ok);
}

/** Returns how many fires have now failed in a row (0 after a success). */
function recordFireOutcome_(props, ok) {
  return bumpCounter_(props, PROP_FIRE_FAILURES, ok);
}

function bumpCounter_(props, key, ok) {
  if (ok) {
    // Only write on a transition, so the once-a-minute happy path costs no property quota.
    if (props.getProperty(key)) {
      props.deleteProperty(key);
    }
    return 0;
  }
  var next = (parseInt(props.getProperty(key), 10) || 0) + 1;
  props.setProperty(key, String(next));
  return next;
}

function alreadyFired_(props, messageId) {
  return firedIds_(props).indexOf(messageId) !== -1;
}

function firedIds_(props) {
  var raw = props.getProperty(PROP_FIRED_IDS);
  if (!raw) {
    return [];
  }
  try {
    var ids = JSON.parse(raw);
    return Array.isArray(ids) ? ids : [];
  } catch (err) {
    return [];
  }
}

function rememberFiredId_(props, messageId) {
  var ids = firedIds_(props);
  ids.push(messageId);
  props.setProperty(PROP_FIRED_IDS, JSON.stringify(ids.slice(-FIRED_IDS_KEPT)));
}

/**
 * A fire the endpoint keeps rejecting means no alert will ever arrive, and the only other record
 * is an Executions log nobody reads. Say so by email, but no more than once per cooldown.
 */
function maybeEscalate_(props, failuresInARow, subject, detail) {
  if (failuresInARow < FIRE_FAILURES_BEFORE_EMAIL) {
    return;
  }
  var now = Date.now();
  var last = parseInt(props.getProperty(PROP_LAST_ESCALATION), 10) || 0;
  if (now - last < ESCALATION_COOLDOWN_MS) {
    return;
  }
  var address = Session.getEffectiveUser().getEmail();
  if (!address) {
    return;
  }
  try {
    MailApp.sendEmail(
      address,
      'FF trade doorbell — cannot reach the trade routine',
      'The doorbell found an ESPN trade proposal but the fire endpoint rejected it ' +
        failuresInARow +
        ' times in a row.\n\n' +
        'Proposal: ' +
        subject +
        '\nLast response: ' +
        detail +
        '\n\n' +
        'HTTP 401/403 means the fire token was rotated; HTTP 404 means the trigger id is wrong or the\n' +
        'routine was deleted. Either way, fix the Script Property in the FF trade doorbell project:\n' +
        'https://script.google.com\n\n' +
        'The offer is still in ESPN and will appear in tomorrow morning\'s briefing regardless.\n'
    );
    props.setProperty(PROP_LAST_ESCALATION, String(now));
    console.log('Emailed ' + address + ' about the repeated fire failure.');
  } catch (err) {
    console.log('Could not send the escalation email: ' + err);
  }
}

/**
 * Run by hand from the editor to prove the fire path works end to end. With no pending offers the
 * routine stops without emailing, so this is safe to run any time.
 */
function fireTestOffer() {
  var props = PropertiesService.getScriptProperties();
  var routineId = props.getProperty('FF_TRADE_ROUTINE_ID');
  var token = props.getProperty('FF_ROUTINE_FIRE_TOKEN');
  if (!routineId || !token) {
    console.log('Missing Script Property FF_TRADE_ROUTINE_ID or FF_ROUTINE_FIRE_TOKEN.');
    return;
  }
  var result = fireRoutine_(routineId, token, 'doorbell self-test (no email expected)', new Date().toISOString());
  console.log(result.ok ? 'Fire succeeded: ' + result.detail : 'Fire FAILED: ' + result.detail);
}

/** Clears the doorbell's bookkeeping (failure counters and fired message ids). */
function resetDoorbellState() {
  var props = PropertiesService.getScriptProperties();
  [PROP_FAILED_RUNS, PROP_FIRE_FAILURES, PROP_LAST_ESCALATION, PROP_FIRED_IDS].forEach(function (key) {
    props.deleteProperty(key);
  });
  console.log('Doorbell state cleared. Script Properties FF_TRADE_ROUTINE_ID / FF_ROUTINE_FIRE_TOKEN untouched.');
}
