/**
 * Gmail doorbell for ESPN trade proposals.
 *
 * ESPN emails "A Trade Proposal in Your ESPN Fantasy Football League" within seconds of a proposal.
 * This script runs every minute, finds such emails that have not been handled yet, and fires the
 * "FF trade offer" routine. The routine re-reads ESPN itself, so the payload is only a doorbell.
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

function checkForTradeOffers() {
  var props = PropertiesService.getScriptProperties();
  var routineId = props.getProperty('FF_TRADE_ROUTINE_ID');
  var token = props.getProperty('FF_ROUTINE_FIRE_TOKEN');
  if (!routineId || !token) {
    console.log('Missing Script Property FF_TRADE_ROUTINE_ID or FF_ROUTINE_FIRE_TOKEN; doing nothing.');
    return;
  }

  var threads = GmailApp.search(SEARCH, 0, MAX_THREADS);
  if (threads.length === 0) {
    return;
  }
  var label = getOrCreateLabel_(LABEL_NAME);

  threads.forEach(function (thread) {
    var messages = thread.getMessages().filter(function (m) {
      return isProposal_(m);
    });
    if (messages.length === 0) {
      // Thread matched on an older message; nothing new to announce.
      thread.addLabel(label);
      return;
    }
    var msg = messages[messages.length - 1];
    var subject = msg.getSubject();
    var date = msg.getDate().toISOString();
    var ok = fireRoutine_(routineId, token, subject, date);
    if (ok) {
      thread.addLabel(label);
      console.log('Fired routine for "' + subject + '" (' + date + '); labeled ' + LABEL_NAME + '.');
    } else {
      console.log('Fire failed for "' + subject + '" (' + date + '); will retry next run.');
    }
  });
}

function isProposal_(message) {
  var from = (message.getFrom() || '').toLowerCase();
  var subject = message.getSubject() || '';
  return from.indexOf('fantasy@espnmail.com') !== -1 && subject.indexOf('Trade Proposal') !== -1;
}

function fireRoutine_(routineId, token, subject, date) {
  var url = 'https://api.anthropic.com/v1/claude_code/routines/' + encodeURIComponent(routineId) + '/fire';
  var body = {
    text: 'ESPN emailed a new trade proposal (' + subject + ', ' + date + '). Re-read ESPN and evaluate.',
  };
  var response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      'anthropic-beta': 'experimental-cc-routine-2026-04-01',
      'anthropic-version': '2023-06-01',
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  if (code >= 200 && code < 300) {
    return true;
  }
  console.log('Fire endpoint returned HTTP ' + code + ': ' + String(response.getContentText()).slice(0, 500));
  return false;
}

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}
