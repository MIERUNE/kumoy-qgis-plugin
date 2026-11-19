# Integration tests (running Kumoy server)

These tests run the plugin's real code paths (API client, device login, data
providers, Processing tools, map storage, presigned uploads and downloads)
against a Kumoy server that is already running, at any URL. Nothing in
`kumoy.api` is mocked, and nothing here starts or prepares a server.

They are skipped unless both variables are set:

| Variable | |
|---|---|
| `KUMOY_E2E_URL` | Server URL, e.g. `https://app.kumoy.io` |
| `KUMOY_E2E_TEAM_ID` | A team you are an Editor of. Use a team for testing only |

Optional:

| Variable | |
|---|---|
| `KUMOY_E2E_TOKEN` | Access token to reuse (valid for 1 hour). Without it the run asks you to log in (below) and prints the token |
| `KUMOY_E2E_OTHER_TOKEN` | Token of a user outside the team, for the permission (403) check |
| `KUMOY_E2E_INTERACTIVE=1` | Also run the tests that need another login each (login dialog, sign-out, logout) |
| `KUMOY_E2E_LOGIN_TIMEOUT` | Seconds to wait for a login approval (default 300) |

Logging in uses the plugin's device flow: the run prints a URL and a code,
and waits until you approve them in the browser, as in the login dialog.

```sh
docker run --rm -it -v "$(pwd)":/plugin -w /plugin \
  -e QT_QPA_PLATFORM=offscreen \
  -e KUMOY_E2E_URL=https://app.kumoy.io -e KUMOY_E2E_TEAM_ID=<team id> \
  -e KUMOY_E2E_TOKEN \
  qgis/qgis:3.44 sh -c "
    pip3 install --break-system-packages pytest pytest-qgis &&
    python3 -m pytest tests/integration -v"
```

For a server on your machine, add `--network host`.

What the run changes on the server: it creates a project named `e2e-<random>`
in the team, works with vectors, rasters and maps inside it (a few thousand
features and small rasters, counted against the organization's storage), and
deletes the project at the end. An interrupted run can leave the project
behind.

Run `tests/integration` on its own: the unit tests register a stub under the
`kumoy` provider key, which can be registered only once per process.
