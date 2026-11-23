"""What the ATS sweep does with a message that RESOLVES an application: its phrase class, and whether a re-run moves it.

design-inbound-resolution.md §2 amendment D1: a resolving message is its own idempotency mark, so a status write that
never landed is re-attempted by the next `reconcile.py --ats` run. That retry applies ONLY a `forward` move
(`applications.status_advance`, dev #542's monotone floor). A message whose class equals the recorded status, or sits
behind it, or matches no single phrase class, is never moved by a re-run, by design.

⭐ dev #1028 (public #269) — `check_followups.py` listed every resolving message newer than its application's
`status_on` as UNRESOLVED INBOUND and named one remedy, "re-run reconcile.py --ats", which the no-backward-move rule
refused every time for most of them: 11 rows on one profile could never be drained. `retry_verdict` answers, from the
row alone and the same classifier the sweep uses, whether that remedy would clear the row: only `retry` rows are
UNRESOLVED (a re-run applies them); every other verdict is HELD, and its remedy is the owner's answer to the ask the
sweep filed (a status-conflict ask, or an unresolved-mail ask), never another run.
"""

RETRY = "retry"
HELD_WHY = {
    "same": "the record already says what the message says",
    "backward": "the message is behind the recorded status (the no-backward-move rule)",
    "sideways": "the message names a different ending than the record",
    "unknown": "a status the engine cannot order",
    "unclassified": "the message matches no single status phrase",
    "withdrawn": "you withdrew; the employer's later mail does not reopen it",
}


def classify_status_phrase(text_low, status_phrases):
    """§3.3 — exactly one status class hit -> (status, False). Zero, or two at once ->
    (None, ambiguous_bool). `status_phrases`: dict status -> [phrase, ...]."""
    hits = []
    for status, phrases in (status_phrases or {}).items():
        for p in phrases or ():
            if p and str(p).lower() in text_low:
                hits.append(status)
                break
    uniq = sorted(set(hits))
    if len(uniq) == 1:
        return uniq[0], False
    return None, bool(uniq)


def retry_verdict(message, app, status_phrases, status_advance):
    """`RETRY` when the D1 retry pass would apply this message's status to `app`, else the key of `HELD_WHY` naming why
    it never will. `status_advance` is `applications.status_advance` (passed in: this module imports no entry point)."""
    text = ("%s\n%s" % (message.get("subject") or "", message.get("body") or "")).lower()
    status, ambiguous = classify_status_phrase(text, status_phrases)
    if status is None or ambiguous:
        return "unclassified"
    if (app or {}).get("status") == "withdrawn":
        return "withdrawn"
    verdict = status_advance((app or {}).get("status"), status)
    return RETRY if verdict == "forward" else verdict


def split_unresolved(messages, app_by_id, status_phrases, status_advance, date_part):
    """(unresolved, held) over the resolving messages newer than their application's `status_on`. `unresolved` holds
    `(message id, application id, sent_on, status, status_on)` for each row a `reconcile.py --ats` re-run moves (D1's own
    window); `held` counts the rest by their `HELD_WHY` key. A dangling `resolves` is validate_data.py's to refuse."""
    unresolved, held = [], {}
    for m in messages:
        app = app_by_id.get(m.get("resolves")) if m.get("resolves") else None
        if app is None:
            continue
        msg_date, app_date = date_part(m.get("sent_on")), date_part(app.get("status_on"))
        if not msg_date or (app_date and app_date >= msg_date):
            continue
        verdict = retry_verdict(m, app, status_phrases, status_advance)
        if verdict == RETRY:
            unresolved.append((m.get("id"), m.get("resolves"), m.get("sent_on"), app.get("status"), app.get("status_on")))
        else:
            held[verdict] = held.get(verdict, 0) + 1
    return unresolved, held


def report_lines(unresolved, held):
    """The follow-up check's lines for both: a remedy that clears each UNRESOLVED row, and the answer each HELD one needs."""
    lines = []
    if unresolved:
        lines += ["", "=" * 72, "UNRESOLVED INBOUND — a message resolved an application; the status never moved", "=" * 72,
                  "  D1: the message write landed but the status write did not (refused, rolled back, or the",
                  "  process died between the two). Re-run reconcile.py --ats: it re-attempts exactly these, and",
                  "  each one is a forward move it applies.", ""]
        lines += ["  - message %s -> application %s (sent %s; status %r since %s)" % row for row in unresolved]
    for why, n in sorted(held.items()):
        lines.append("  held inbound: %d resolving message(s) a re-run never moves — %s. Not a failure: answer the "
                     "ATS ask in Your Move, or record the status yourself (dev #1028)." % (n, HELD_WHY[why]))
    return lines
