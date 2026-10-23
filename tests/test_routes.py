"""The HTTP API surface: every route is registered (the JS depends on these paths),
and the route package doesn't shadow the data modules it serves."""
import io
import logging
import shutil
import sys

import test_shared as T

check = T.check

EXPECTED = """
DELETE /recipes/{rid}
DELETE /registry/{name}
GET /archive/moves
GET /archive/status
GET /archive/summary
GET /archive/thumb
GET /duplicates
GET /ext/hello
GET /ext/jobs
GET /ext/model
GET /identify
GET /jobs
GET /library
GET /library/description
GET /library/usage
GET /organize/history
GET /partials
GET /partials/summary
GET /storage/history
GET /preview/{fid}
GET /recipes
GET /recipes/{rid}
GET /recipes/{rid}/thumb
GET /recipes/{rid}/image
POST /recipes/{rid}/picture
GET /registry
GET /runs/images
GET /status
GET /tiering/events
GET /tiering/job
GET /tiering/lm-paths
GET /tiering/plan
GET /updates
GET /workflows/health
PATCH /recipes/{rid}
POST /bridge/apply
POST /bridge/plan
POST /config
POST /download
POST /duplicates/hardlink
POST /duplicates/quarantine
POST /duplicates/scan
POST /archive/cancel
POST /archive/move
POST /archive/move-plan
POST /archive/start
POST /archive/undo-move
POST /civarchive/lookup
POST /ext/civarchive
POST /ext/companion-download
POST /ext/companions
POST /ext/download
POST /ext/download-url
POST /gallery/open
POST /gallery/claim
POST /ext/lookup
POST /recipe/link
POST /recipe/link-url
POST /updates/compare
POST /hf/details
POST /identify
POST /identify/cancel
POST /jobs/clear
POST /jobs/{jid}/cancel
POST /jobs/{jid}/retry
POST /library/description/fetch
POST /library/notes
POST /organize/apply
POST /organize/plan
POST /organize/undo
POST /partials/delete
POST /recipe/analyze
POST /recipe/from-output
POST /recipe/from-lm
POST /recipe/plan
POST /recipes
POST /registry
POST /resolve
POST /resolve-url
POST /scan
POST /tiering/archive
POST /tiering/restore
POST /updates/cancel
POST /updates/candidate
POST /updates/check
POST /updates/dismiss
POST /vram
POST /workflows/scan
POST /workflows/sources
""".split("\n")


def main():
    base, user = T.fake_install("Routes")
    smf = T.load_smf(base, user)
    from aiohttp import web

    log = io.StringIO()
    handler = logging.StreamHandler(log)
    logging.getLogger().addHandler(handler)
    rt = web.RouteTableDef()
    smf.routes.register(rt)
    logging.getLogger().removeHandler(handler)

    got = sorted(f"{r.method} {r.path.replace(smf.routes.P, '', 1)}" for r in rt)
    want = sorted(x.strip() for x in EXPECTED if x.strip())
    check(got == want, f"every API route registered once ({sorted(set(want) ^ set(got)) or 'ok'}; {len(got)} routes)")
    check(len(got) == len(set(got)), "no route registered twice")
    check(smf.routes.tiering is smf.tiering and smf.routes.library is smf.library and smf.routes.recipes is smf.recipes,
          "route package doesn't shadow the data modules (tiering, library, recipes)")
    check("storage tiers unavailable" not in log.getvalue(), "startup installs the storage tiers without errors")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
