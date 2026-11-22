"""What a build says: the refusal (`BuildError`) and the three results (`Acceptance`, `BuildResult`,
`PublishResult`)."""


class BuildError(ValueError):
    """The build refuses. The message is one line and names the cause.

    `path`, `lineno` and `fix` (design-site-fidelity section 4.1) say where, on which line when the check
    knows it, and the one-line remedy; `build.accept` turns them into a `siteconfig.Problem`. `problems`
    is the whole list when the build refused for several things at once (the message is then the join of
    theirs; with one problem it is exactly that problem's message)."""

    def __init__(self, message="", path=None, lineno=None, fix=None, problems=None):
        ValueError.__init__(self, message)
        self.path = path
        self.lineno = lineno
        self.fix = fix
        self.problems = list(problems or [])


class Acceptance(object):
    """What `accept` returns: every `problem` (a `siteconfig.Problem`, ordered by path), the `notes`, and
    what was built in memory when it got that far (`cfg`, `model`, `output` {output path: bytes}, `pages`).
    `warnings` is a list of the same `make_problem` shape, kept APART from `problems`: `problems` means the
    build refuses, a warning means it builds and says what it does not publish (a stray `.md` or folder in a
    piece folder, an unknown piece key; dev #885, dev #882). Empty `problems` with warnings is still an
    accepted tree whose output bytes the warnings never change; `adopt check` may refuse one. `used` is the sorted repo
    paths the build read to make that output (`provenance.used`, design-adopt-parity-2 rule S1); empty when the run
    stopped before it built."""

    def __init__(self, problems, notes, cfg, model, output, pages, warnings=None, used=None):
        self.problems = problems
        self.notes = notes
        self.warnings = list(warnings or [])
        self.used = list(used or [])
        self.cfg = cfg
        self.model = model
        self.output = output
        self.pages = pages


class BuildResult(object):
    """What a build produced. `preview_build` returns exactly this: it has no digest."""

    def __init__(self, out_dir, files, pages, site_url, drafts, notes, warnings=None):
        self.out_dir = out_dir
        self.files = files          # sorted output paths (NFC, relative)
        self.pages = pages          # sorted [(output path, kind)]
        self.site_url = site_url
        self.drafts = drafts
        self.notes = notes
        self.warnings = list(warnings or [])      # `Acceptance.warnings` of this build (dev #885, dev #882)


class PublishResult(BuildResult):
    """What `publish_build` returns: a BuildResult plus the digest and the site kind it covers."""

    def __init__(self, out_dir, files, pages, site_url, drafts, notes, digest, site_kind="portfolio",
                 warnings=None):
        BuildResult.__init__(self, out_dir, files, pages, site_url, drafts, notes, warnings)
        self.digest = digest
        self.site_kind = site_kind
