"""guarding.texts -- the words the guard says and the tables that pick them: the policy sentences, the ask texts, what each
matched command is called (`KINDS`), and which publish outranks which (`RANK`). Constants only; `deploying.headcheck` reads
`REMOTE_POLICY` from here, so the publish script and the guard say one sentence.
"""
REMOTE_POLICY = ("site-studio publishes only from a session on your own computer. "
                 "Open this repo there and type /site-studio:publish.")
ASK_MODES = ("default", "acceptEdits", "plan", "auto")
NOT_ASKED_MODES = ("bypassPermissions", "dontAsk")
DENY_NO_ASK = ("Publishing asks you every time, and this session is set not to ask. "
               "Switch the permission mode and run /site-studio:publish.")
REPORT_REMOTE_POLICY = ("site-studio files reports only from a session on your own computer. "
                        "Open this repo there and run adopt.py report --file.")
REPORT_DENY_NO_ASK = ("Filing a report asks you every time, and this session is set not to ask. Run adopt.py "
                      "report to print the reports, then switch the permission mode to file them.")
REPORT_ASK = ("File the pending site-studio adopt reports as public issues on the marketplace? Each carries "
              "structure and version numbers only, never your site's text, names or paths. `adopt.py report` "
              "prints exactly what would be filed.")
SUGGESTION_REMOTE_POLICY = ("site-studio files a look suggestion only from a session on your own computer. Open this repo there "
                            "and run adopt.py report --suggestion ID to read it first.")
SUGGESTION_DENY_NO_ASK = ("Filing a look suggestion asks you every time, and this session is set not to ask. Run adopt.py report "
                          "--suggestion ID to print it, then switch the permission mode to file it.")
SUGGESTION_ASK = ("File this one look suggestion as a public issue on the marketplace? It carries the shape of one construct of your "
                  "look with every class name, id, address and word taken out, and the numbers adopt measured. "
                  "`adopt.py report --suggestion %s` prints exactly what would be filed.")
SUGGESTION_SHOWN = " Digest %s. It begins:\n%s"
SUGGESTION_NOT_SHOWN = " Digest %s. The text could not be printed here (%s): run that command to read it before you allow this."
SUGGESTION_OTHER_DIGEST = " The digest in this command is not the text's now (%s), so adopt.py will refuse to file it."
SHOWN_LINES = 12              # the body lines the suggestion ask carries (round 2, M4)
APPLY_REMOTE_POLICY = ("site-studio adopts a site only from a session on your own computer. "
                       "Open this repo there and run adopt.py apply.")
APPLY_DENY_NO_ASK = ("Adopting publishes your site and retires your old builder, so it asks you every time, and this session "
                     "is set not to ask. Run adopt.py apply --dry-run to see what it would do, then switch the permission "
                     "mode to run it.")
APPLY_ASK = ("Adopt this site: publish it to %s (public forever), wait for GitHub Pages to build it, then archive your old "
             "builder and push that commit to this repo's main branch? Nothing is published or pushed if a step before "
             "the push stops. If no review covers the build, parity EQUAL and the automated privacy scans stand in for one, and "
             "the run says so. `adopt.py apply --dry-run` shows what it would do.")
APPLY_ASK_NO_REPO = "the public repo named in site/site.json (it could not be read here)"
KINDS = {                     # what each match is called in the texts that name the command
    "confirm": {"name": "deploy.py", "does": "publishes", "not": "a publish", "run": "run /site-studio:publish",
                "unknown": "Run /site-studio:publish from a session in default or acceptEdits mode.",
                "who": "Publishing", "cmd": "deploy.py --confirm"},
    "report": {"name": "adopt.py report", "does": "files reports", "not": "one that files reports",
               "run": "run the command again",
               "unknown": "Run adopt.py report --file from a session in default or acceptEdits mode.",
               "who": "Filing a report", "cmd": "adopt.py report --file"},
    "suggestion": {"name": "adopt.py report --suggestion", "does": "files one look suggestion",
                   "not": "one that files a look suggestion", "run": "run the command again",
                   "unknown": "Run adopt.py report --suggestion ID --file from a session in default or acceptEdits mode.",
                   "who": "Filing a look suggestion", "cmd": "adopt.py report --suggestion --file"},
    "apply": {"name": "adopt.py apply", "does": "adopts the site (publishes it and retires the old builder)",
              "not": "an adoption", "run": "run adopt.py apply again",
              "unknown": "Run adopt.py apply from a session in default or acceptEdits mode.",
              "who": "Adopting", "cmd": "adopt.py apply"},
}
RANK = {"report": 0, "suggestion": 0, "apply": 1, "confirm": 2}      # when one command holds several, the larger publish decides
RELEASED_SHOWN = 3            # released addresses the ask names before "+N more"
