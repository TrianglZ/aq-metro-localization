# aq-metro-localization

The single source of truth for all Arabic (`ar`) and English (`en`) UI text used across the AQ Metro native mobile apps — iOS (Swift) and Android (Kotlin).

Instead of duplicating strings across two codebases and letting them drift out of sync, every piece of user-facing copy lives in one master dictionary in this repository. A GitHub Action converts that dictionary into native platform formats automatically, and the mobile apps pull the generated files at build time — no manual copy-pasting, no Python required on developer machines.

---

## How It Works

```
┌─────────────────────────┐
│  localization_hub.json  │   ← Translators edit this file
│   (master dictionary)   │
└────────────┬─────────────┘
             │ push / merge to main
             ▼
┌─────────────────────────┐
│   GitHub Action (CI)    │   ← Runs automatically on every change
│  Python generator script│
└────────────┬─────────────┘
             │ commits generated files
             ▼
┌─────────────────────────┐
│        /outputs         │   ← Pre-generated, ready-to-use native files
│  en.strings / ar.strings│
│  strings-en.xml / -ar.xml│
└────────────┬─────────────┘
             │ downloaded at build time
             ▼
┌─────────────────────┐   ┌─────────────────────┐
│   iOS (Xcode)       │   │  Android (Gradle)   │
│  Online Sync /      │   │  Online Sync /       │
│  Offline Fallback   │   │  Offline Fallback    │
└─────────────────────┘   └─────────────────────┘
```

1. **Translators and PMs** edit `localization_hub.json` — the only file anyone should touch by hand.
2. **A GitHub Action** detects the change, runs a Python script that parses the JSON, and generates the native formats: `.strings` files for iOS and `.xml` resource files for Android.
3. The generated files are committed to the **`/outputs`** folder on the `main` branch. This folder is the "public API" of this repository — it's what mobile builds actually consume.
4. **Mobile developers never run the Python script locally.** Each project has a small build-time sync script (a Run Script phase in Xcode, a Gradle task in Android) that downloads the latest files from `/outputs` straight into the project before compiling.
5. That sync script follows an **Online Sync / Offline Fallback** strategy: if the machine has internet access, it grabs the freshest strings; if the request fails or times out (no wifi, VPN issues, CI runner with no network, etc.), the build silently falls back to whatever was cached from the last successful sync — the build never breaks because of a network hiccup.

---

## Repository Structure

```
aq-metro-localization/
├── localization_hub.json   # Master dictionary — the only file humans edit
├── /scripts/                # Python generator (invoked by the GitHub Action, not by developers)
│   └── generate_strings.py
├── /outputs/                 # Auto-generated, committed by CI — do not edit by hand
│   ├── en.strings           # iOS — English
│   ├── ar.strings           # iOS — Arabic
│   ├── strings-en.xml       # Android — English (values/)
│   └── strings-ar.xml       # Android — Arabic (values-ar/)
├── .github/
│   └── workflows/
│       └── generate-localization.yml   # CI pipeline that runs on every push to localization_hub.json
└── README.md
```

> ⚠️ **Never hand-edit anything inside `/outputs`.** Those files are regenerated on every merge and any manual changes will be silently overwritten by the next CI run.

---

## For Translators & Content Editors

All content changes happen in a single file: **`localization_hub.json`**.

### File Format

The file is grouped by screen or component module. Each key is a `snake_case` string identifier, and its value is an object containing both language variants:

```json
{
  "OnboardingScreen": {
    "welcome_title": { "ar": "مرحبا بك في مترو الأسكندرية", "en": "Welcome to Alexandria Metro" },
    "btn_next": { "ar": "التالي", "en": "Next" }
  },
  "HomeScreen": {
    "btn_login": { "ar": "تسجيل دخول", "en": "Log In" }
  }
}
```

### Editing Guidelines

- **Group by screen, not by feature.** Keep keys for a given screen (e.g. `HomeScreen`, `SettingsScreen`, `PurchaseTicketScreen`) together under that screen's object so developers can find strings quickly.
- **Use clean, descriptive `snake_case` keys.** Prefix buttons with `btn_`, labels with `label_`, and titles with `_title` for consistency (e.g. `btn_continue`, `label_price`, `onboarding_1_title`).
- **Always provide both `ar` and `en` values.** A key missing either language will cause the generator script to fail validation in CI.
- **Placeholders use curly braces.** Dynamic values (prices, dates, counts) should be written as `{variable_name}` in both languages so they map to the same native format specifier during generation, e.g. `"تنتهي في {time}"` / `"Expires at {time}"`.
- **Don't touch `/outputs`.** If you need a string updated, edit the master JSON — CI takes care of the rest.
- **Open a pull request.** Changes to `localization_hub.json` should go through a PR so the diff is reviewable before merging to `main` (which triggers the generation Action).

Once your PR merges to `main`, the GitHub Action runs automatically, regenerates `/outputs`, and commits the result. No further action is needed from translators — mobile apps will pick up the change on their next build sync.

---

## For Mobile Developers: Build-Time Sync

You should **never** run the Python generator locally, and you should **never** need Python installed to build the app. Each platform has a small sync step that runs automatically as part of the normal build, pulling the latest pre-generated files from `/outputs` on `main`.

Both integrations follow the same **Online Sync / Offline Fallback** rule: try to fetch fresh strings over the network with a short timeout; if that fails for any reason, keep whatever is already cached in the project and continue the build without failing.

### iOS — Xcode Run Script Phase

Add a new **Run Script Phase** in your target's Build Phases (before "Compile Sources"), and paste the following:

```bash
# Define where the output files live in the Xcode project
EN_STRINGS="./AQMetro/Resources/en.lproj/Localizable.strings"
AR_STRINGS="./AQMetro/Resources/ar.lproj/Localizable.strings"

# URLs to your pre-generated files on GitHub
URL_EN="https://raw.githubusercontent.com/[YOUR-ORG]/aq-metro-localization/main/outputs/en.strings"
URL_AR="https://raw.githubusercontent.com/[YOUR-ORG]/aq-metro-localization/main/outputs/ar.strings"

echo "Checking for latest localization files..."

if curl -s -f --connect-timeout 3 "$URL_EN" -o "${EN_STRINGS}.tmp"; then
    mv "${EN_STRINGS}.tmp" "$EN_STRINGS"
    echo "✅ English strings updated."
else
    rm -f "${EN_STRINGS}.tmp"
    echo "⚠️ Offline. Using cached English strings."
fi

if curl -s -f --connect-timeout 3 "$URL_AR" -o "${AR_STRINGS}.tmp"; then
    mv "${AR_STRINGS}.tmp" "$AR_STRINGS"
    echo "✅ Arabic strings updated."
else
    rm -f "${AR_STRINGS}.tmp"
    echo "⚠️ Offline. Using cached Arabic strings."
fi
```

**Notes:**
- Replace `[YOUR-ORG]` with the actual GitHub organization/user name.
- The `--connect-timeout 3` flag caps each request at 3 seconds, so a flaky or absent connection can't stall your build.
- The script downloads to a `.tmp` file first and only `mv`s it into place on success — this prevents a partial/failed download from corrupting your cached strings.
- Commit the initial `Localizable.strings` files to the repo as the "cold start" fallback for a fresh checkout with no network.

### Android — Gradle Task

Add the following task to your module's `build.gradle` (or `build.gradle.kts`, adapted to Kotlin DSL syntax), and hook it into `preBuild`:

```groovy
import java.net.HttpURLConnection
import java.net.URL

tasks.register('downloadLocalization') {
    doLast {
        def enUrl = "https://raw.githubusercontent.com/[YOUR-ORG]/aq-metro-localization/main/outputs/strings-en.xml"
        def arUrl = "https://raw.githubusercontent.com/[YOUR-ORG]/aq-metro-localization/main/outputs/strings-ar.xml"

        def enFile = file("${projectDir}/src/main/res/values/strings.xml")
        def arFile = file("${projectDir}/src/main/res/values-ar/strings.xml")

        println "Checking for latest localization files..."
        try {
            HttpURLConnection connection = (HttpURLConnection) new URL(enUrl).openConnection()
            connection.setConnectTimeout(3000)
            if (connection.getResponseCode() == 200) {
                enFile.text = connection.inputStream.text
                println "✅ English strings updated."
            }

            connection = (HttpURLConnection) new URL(arUrl).openConnection()
            connection.setConnectTimeout(3000)
            if (connection.getResponseCode() == 200) {
                arFile.text = connection.inputStream.text
                println "✅ Arabic strings updated."
            }
        } catch (Exception e) {
            println "⚠️ Offline or connection failed. Building with cached strings."
        }
    }
}

preBuild.dependsOn downloadLocalization
```

**Notes:**
- Replace `[YOUR-ORG]` with the actual GitHub organization/user name.
- `setConnectTimeout(3000)` caps the connection attempt at 3 seconds, matching the iOS behavior.
- Wrapping the whole block in `try/catch` guarantees that any network failure (timeout, DNS error, non-200 response) falls through to the cached `strings.xml` / `values-ar/strings.xml` already in the project — the build never fails because of this task.
- Commit the initial `values/strings.xml` and `values-ar/strings.xml` files to the repo as the "cold start" fallback for a fresh checkout with no network.

---

## Summary of Responsibilities

| Role | Touches | Never touches |
|---|---|---|
| Translators / PMs | `localization_hub.json` | `/outputs`, generator script |
| CI (GitHub Action) | `/outputs` (auto-commit) | `localization_hub.json` |
| iOS developers | Xcode Run Script Phase config | Python script, `localization_hub.json` |
| Android developers | Gradle `downloadLocalization` task | Python script, `localization_hub.json` |

If a string looks wrong in the app, the fix always starts in `localization_hub.json` via a pull request — never in the generated `/outputs` files or in the app's local resource files directly.
