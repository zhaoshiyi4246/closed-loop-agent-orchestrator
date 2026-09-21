# CLAO Native 0.3 Windows candidate

Windows 10/11 x64. Run the **CLAO Native** installer for a per-user installation,
or extract the portable ZIP and open `clao/clao-native.exe`. No administrator,
source checkout, Go, Node, Python, venv, Vite, or Codex development cache is needed
to start the application. The installer creates independent CLAO shortcuts and an
uninstaller. This unsigned candidate may display Windows publisher warnings.

Install Git for Windows and the coding tool you select (for example Codex CLI)
separately, and sign in using that tool's supported account flow. Git, coding tool
accounts and project-specific tools used by your Gate commands are external
prerequisites; they are not silently installed or configured by CLAO. Creating a
task requires a ready tool/account and an explicit source and Gate. Existing tool
account selection is retained; empty isolated test accounts are never the default.

CLAO data and discovery are under `%USERPROFILE%\.clao-ao`, separate from official
AO's `.ao`. This candidate does not contact an AO update feed or publish updates.
Uninstall removes the application; task data is preserved. For rollback, quit CLAO,
retain the complete data directory and related Git workspaces/evidence, uninstall
this candidate and install a previously verified CLAO build. Database-only backups
do not contain all recovery material. Do not open newer task data with an older
version without a compatible backup.

The bundle includes Electron, the derived AO daemon, CPython 3.12.10, the locked
Python runtime dependencies, the native browser helper and the ACP Node runtime.
Original AO Apache-2.0 licensing and bundled dependency notices are retained under
`resources/third-party`; Python and wheel licenses stay beside those components.
The private `python-core.exe` uses a fixed relative search path within the
installation and ignores working-directory/environment imports. The bundled
`python.exe` is on the task PATH and retains normal local module imports for Gate
scripts. Extra project-specific Python dependencies still need their own environment.

Build with `packaging/build-release.ps1 -OutputDirectory <new outside directory>`
from a clean committed checkout. Build-only `-Node`, `-Go`, and `-Python` parameters
can select installed tool executables (Python needs pip). The builder resolves
manifest inputs from HEAD, uses npm lockfiles, checks Python archive/wheel hashes,
and emits an installer, portable ZIP, source record and SHA-256 manifest. It never
publishes. `build-root` is diagnostic build material, not part of the distributable.

Candidate construction is separate from product acceptance. Two clean Windows
environments, installed GUI/task journeys, real supported model profiles and final
owner experience acceptance must be recorded before declaring release complete.
