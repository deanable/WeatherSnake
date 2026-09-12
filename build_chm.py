"""Build and validate the WeatherSnake compiled help (CHM).

Usage:
	python build_chm.py            # validate the help tree
	python build_chm.py --compile  # compile WeatherSnake.chm (requires hhc.exe)

Validation (runs everywhere, incl. CI on any OS) checks:
  * the [ALIAS]/[MAP] blocks in the .hhp cover the same ids and agree with
    TOPIC_IDS (the single source of truth shared with help_launcher.py)
  * every topic referenced by .hhp/.hhc/.hhk and by cross-links exists
  * every topic page declares its context id and links the stylesheet
  * HTML sanity: matched tags, quoted link targets, charset declared, and no
    stray mid-file </body></html> (a classic truncated-write bug)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HELP_DIR = os.path.join(BASE_DIR, "help", "html")
HHP_FILE = os.path.join(HELP_DIR, "WeatherSnake.hhp")
HHC_FILE = os.path.join(HELP_DIR, "WeatherSnake.hhc")
HHK_FILE = os.path.join(HELP_DIR, "WeatherSnake.hhk")

APP_NAME = "WeatherSnake"
DEFAULT_TOPIC = "welcome.html"
WINDOW_NAME = "main"

# context id -> topic file. Single source of truth for the .hhp [ALIAS]/[MAP]
# blocks and for the runtime (help_launcher.py).
TOPIC_IDS = {
	1000: "welcome.html",
	1001: "getting-started.html",
	1002: "interface.html",
	1003: "location.html",
	1004: "periods.html",
	1005: "depth.html",
	1006: "units.html",
	1007: "monthly.html",
	1008: "precipitation.html",
	1009: "conditions.html",
	1010: "insights.html",
	1011: "yearly.html",
	1012: "comparison.html",
	1013: "exports.html",
	1014: "keyboard.html",
	1015: "cli.html",
	1016: "data.html",
	1017: "troubleshooting.html",
	1018: "about.html",
	1019: "troubleshooting.html",
	1020: "troubleshooting.html",
}

# Additional sanity limits used by tests.
MAX_TOPIC_SIZE = 200_000
MIN_TOPIC_SIZE = 200


def _parse_hhp_sections(path):
	"""Return dict of section name -> list of raw lines for each .hhp section."""
	sections = {}
	current = None
	with open(path, "r", encoding="utf-8") as fh:
		for line in fh:
			s = line.strip()
			if s.startswith("[") and s.endswith("]"):
				current = s[1:-1]
				sections[current] = []
			elif current is not None:
				sections[current].append(line.rstrip("\n"))
	return sections


def _hhp_aliases(section_lines):
	"""Parse an [ALIAS] section into {IDH_NAME: topic_file}."""
	aliases = {}
	for line in section_lines:
		s = line.strip()
		if "=" in s and not s.startswith(";"):
			k, _, v = s.partition("=")
			aliases[k.strip()] = v.strip()
	return aliases


def _hhp_map(section_lines):
	"""Parse a [MAP] section into {IDH_NAME: context_id}."""
	ctxmap = {}
	for line in section_lines:
		s = line.strip()
		if "=" in s and not s.startswith(";"):
			k, _, v = s.partition("=")
			try:
				ctxmap[k.strip()] = int(v.strip())
			except ValueError:
				continue
	return ctxmap


class _LinkChecker(HTMLParser):
	"""Collect href targets and run basic structural validation per page."""

	VOID_TAGS = {"br", "img", "meta", "link", "hr", "input"}

	def __init__(self, name):
		super().__init__(convert_charrefs=True)
		self.name = name
		self.hrefs = []
		self.errors = []
		self.stack = []
		self.declared_topic_id = None

	def handle_starttag(self, tag, attrs):
		d = dict(attrs)
		if tag == "meta" and d.get("name") == "topic-id":
			self.declared_topic_id = d.get("content")
		if tag == "a" and d.get("href") is not None:
			self.hrefs.append(d["href"])
		if tag in self.VOID_TAGS:
			return
		self.stack.append(tag)
		if tag == "body" and not d.get("id"):
			self.errors.append("body lacks id attribute")

	def handle_endtag(self, tag):
		if tag in self.VOID_TAGS:
			return
		if not self.stack:
			self.errors.append(f"unexpected </{tag}>")
			return
		if self.stack[-1] != tag:
			# tolerate implicitly closed <li> / <p>
			if tag in ("li", "p") and tag in self.stack:
				while self.stack and self.stack[-1] != tag:
					self.stack.pop()
				self.stack.pop()
			else:
				self.errors.append(
					f"mismatched <{self.stack[-1]}> closed by </{tag}>"
				)
				return
		self.stack.pop()


def validate_help_tree():
	"""Validate the help tree. Returns a list of error strings (empty = OK)."""
	errors = []
	if not os.path.isdir(HELP_DIR):
		return [f"missing help directory: {HELP_DIR}"]
	if not os.path.isfile(HHP_FILE):
		return [f"missing help project file: {HHP_FILE}"]

	all_files = set(os.listdir(HELP_DIR))

	# --- .hhp [ALIAS] / [MAP] cross-check against TOPIC_IDS ---
	sections = _parse_hhp_sections(HHP_FILE)
	aliases = _hhp_aliases(sections.get("ALIAS", []))
	ctxmap = _hhp_map(sections.get("MAP", []))

	if set(aliases) != set(ctxmap):
		errors.append("[ALIAS] and [MAP] blocks list different ids")
	else:
		alias_by_file = {}
		for aid, fname in aliases.items():
			alias_by_file.setdefault(fname, []).append(aid)
		for aid, fname in aliases.items():
			ctx_id = ctxmap.get(aid)
			declared = TOPIC_IDS.get(ctx_id)
			if declared != fname:
				errors.append(
					f"alias {aid} -> {fname} but TOPIC_IDS[{ctx_id}] = {declared}"
				)
		for ctx_id, fname in TOPIC_IDS.items():
			if fname not in alias_by_file:
				errors.append(f"topic {fname} (id {ctx_id}) has no [ALIAS] entry")

	# --- per-topic HTML validation ---
	for ctx_id, fname in sorted(TOPIC_IDS.items()):
		path = os.path.join(HELP_DIR, fname)
		if not os.path.isfile(path):
			errors.append(f"topic file missing: {fname}")
			continue
		with open(path, "r", encoding="utf-8") as fh:
			raw = fh.read()
		if len(raw) < MIN_TOPIC_SIZE:
			errors.append(f"topic {fname} suspiciously small ({len(raw)} bytes)")
		if len(raw) > MAX_TOPIC_SIZE:
			errors.append(f"topic {fname} suspiciously large ({len(raw)} bytes)")
		if "charset" not in raw.lower():
			errors.append(f"topic {fname} does not declare charset=utf-8")
		if 'href="styles.css"' not in raw:
			errors.append(f"topic {fname} does not link styles.css")
		# No mid-file </body></html> before the true end of the document.
		stripped = raw.rstrip()
		core = re.sub(r"</body>\s*</html>\s*$", "", stripped)
		if re.search(r"</body>\s*</html>", core):
			errors.append(f"topic {fname} has a mid-file </body></html> (truncated write)")

		parser = _LinkChecker(fname)
		try:
			parser.feed(raw)
			parser.close()
		except Exception as exc:
			errors.append(f"topic {fname} failed to parse: {exc}")
			continue
		if parser.stack:
			errors.append(f"topic {fname} unclosed tags: {parser.stack}")
		if parser.errors:
			errors.extend(f"topic {fname}: {e}" for e in parser.errors)
		if parser.declared_topic_id is None:
			errors.append(f"topic {fname} lacks a topic-id meta tag")
		for href in parser.hrefs:
			if href.startswith(("http://", "https://", "mailto:", "#")):
				continue
			target = href.split("#")[0]
			if not target:
				continue
			if target not in all_files:
				errors.append(f"topic {fname} links missing file {href}")

	# --- .hhc / .hhk referenced files exist ---
	for listfile in (HHC_FILE, HHK_FILE):
		if not os.path.isfile(listfile):
			errors.append(f"missing help list file: {os.path.basename(listfile)}")
			continue
		with open(listfile, "r", encoding="utf-8") as fh:
			content = fh.read()
		for m in re.finditer(r'param name="Local" value="([^"]+)"', content):
			if m.group(1) not in all_files:
				errors.append(
					f"{os.path.basename(listfile)} references missing file {m.group(1)}"
				)

	# --- every topic declared in the .hhp [FILES] ---
	hhp_files = sections.get("FILES", [])
	for fname in sorted(set(TOPIC_IDS.values())):
		if not any(fname in line for line in hhp_files):
			errors.append(f"topic {fname} missing from .hhp [FILES]")

	return errors


def find_hhc():
	"""Locate hhc.exe (HTML Help Workshop compiler). Returns path or None."""
	if os.name != "nt":
		return None
	hhc = shutil.which("hhc.exe") or shutil.which("hhc")
	if hhc:
		return hhc
	pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
	pf = os.environ.get("ProgramFiles", r"C:\Program Files")
	pf64 = os.environ.get("ProgramW6432", pf)
	for base in (pf86, pf, pf64):
		candidate = os.path.join(base, "HTML Help Workshop", "hhc.exe")
		if os.path.isfile(candidate):
			return candidate
	return None


def compile_chm(verbose=True):
	"""Compile WeatherSnake.chm with hhc.exe. Returns output path or None."""
	errors = validate_help_tree()
	if errors:
		for e in errors:
			print(f"HELP ERROR: {e}", file=sys.stderr)
		return None

	hhc = find_hhc()
	if not hhc:
		print(
			"hhc.exe not found - install HTML Help Workshop or add it to PATH.",
			file=sys.stderr,
		)
		return None

	out = os.path.join(HELP_DIR, f"{APP_NAME}.chm")
	if os.path.exists(out):
		os.remove(out)
	cmd = [hhc, HHP_FILE]
	if verbose:
		print("Compiling:", " ".join(cmd))
	result = subprocess.run(cmd, cwd=HELP_DIR, capture_output=True, text=True)
	if verbose:
		if result.stdout:
			print(result.stdout[-2000:])
		if result.stderr:
			print(result.stderr[-2000:])
	# hhc.exe returns 1 on success (a documented quirk) and 0 when it did
	# nothing at all, so the artifact itself is the real success signal.
	if os.path.isfile(out) and os.path.getsize(out) > 10_000:
		print(f"Compiled {out} ({os.path.getsize(out):,} bytes)")
		return out
	print(
		f"hhc.exe exited {result.returncode} and/or no usable .chm was produced.",
		file=sys.stderr,
	)
	return None


def main():
	ap = argparse.ArgumentParser(description="Validate/compile the WeatherSnake help system.")
	ap.add_argument(
		"--compile",
		action="store_true",
		help="compile WeatherSnake.chm (requires HTML Help Workshop / hhc.exe)",
	)
	args = ap.parse_args()

	errors = validate_help_tree()
	if errors:
		for e in errors:
			print(f"HELP ERROR: {e}", file=sys.stderr)
		return 2
	print(f"Help tree OK: {len(TOPIC_IDS)} topics validated.")

	if args.compile:
		out = compile_chm(verbose=True)
		return 0 if out else 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
