"""The append-only "prior" lists of an opportunity row: `listed_pay_prior` (every `listed_pay` a supersede moved aside, 0.88.0) and `fit_prior` (every
`fit` a withdrawal moved aside, 0.94.0).

`listed_pay_prior` moved here from `validate_data.py` unedited in jobsearch 0.94.0 (dev 1063) so the validator, which is over its budget, could take
`fit_prior` without growing. `fit_prior` (docs/design-role-first.md 0, 6.3): when a read is withdrawn, a `fit` dated between the read and the withdrawal
is moved to `fit_prior` (a list, oldest first), so research runs again against a read that stands. Each entry is the `fit` object as it was and is checked
as `fit` is: an ISO `analyzed_on`, a closed `jd_source` prefix and a non-empty list of requirements. Only the withdrawal writes it; the row carries it
only after the 0.94.0 pin (an older engine refuses an unknown key).

Capability module of `validate_data.py`. Python 3.9+, standard library only."""

from validation.basics import is_date
from validation.jd_source import check_jd_source
from validation.pay import check_listed_pay
from validation.requirement_rules import check_requirement


def check_listed_pay_prior(prior, label, problems):
    """dev #846 (0.88.0, design 4.2): the append-only list of every `listed_pay` a supersede moved aside (a non-empty list of listed_pay objects)."""
    if not isinstance(prior, list) or not prior:
        problems.append("%s: listed_pay_prior must be a non-empty list of superseded listed_pay objects (absent means "
                        "nothing was superseded) -- got %r" % (label, prior))
        return
    for i, entry in enumerate(prior):
        check_listed_pay(entry, "%s listed_pay_prior[%d]" % (label, i), problems, prior=True)


def check_fit_prior(prior, label, problems):
    """jobsearch 0.94.0 (dev 1063, design-role-first.md 6.3): `fit_prior` is a non-empty list of `fit` objects a withdrawal moved aside. Absent
    means nothing was withdrawn under a fit; an empty list is refused (omit the key instead)."""
    if not isinstance(prior, list) or not prior:
        problems.append("%s: fit_prior must be a non-empty list of the fit objects a withdrawal moved aside (absent means none was) -- got %r"
                        % (label, prior))
        return
    for i, entry in enumerate(prior):
        el = "%s fit_prior[%d]" % (label, i)
        if not isinstance(entry, dict):
            problems.append("%s: must be a fit object -- got %s" % (el, type(entry).__name__))
            continue
        if not is_date(entry.get("analyzed_on", "")):
            problems.append("%s: analyzed_on not ISO -- %r" % (el, entry.get("analyzed_on")))
        check_jd_source(entry.get("jd_source"), el, problems)
        reqs = entry.get("requirements")
        if not isinstance(reqs, list) or not reqs:
            problems.append("%s: requirements must be a non-empty list" % el)
        else:
            for j, q in enumerate(reqs):
                check_requirement(q, "%s requirements[%d]" % (el, j), problems)


def check_opportunity_priors(r, label, problems):
    """The prior lists `r` carries, each checked when present: `listed_pay_prior` and `fit_prior`."""
    if "listed_pay_prior" in r:
        check_listed_pay_prior(r["listed_pay_prior"], label, problems)
    if "fit_prior" in r:
        check_fit_prior(r["fit_prior"], label, problems)
