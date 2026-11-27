"""Provider priority, identity, persistence and usage-isolation tests (no network)."""
import copy, json, os, sys, tempfile, types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The tests never record audio; the CI image has no PortAudio, so provide the import-only surface core needs.
if "sounddevice" not in sys.modules:
    try: import sounddevice  # noqa: F401
    except Exception:
        sd = types.ModuleType("sounddevice")
        sd.InputStream = sd.RawOutputStream = sd.RawInputStream = object
        sys.modules["sounddevice"] = sd

from ai_overlay_lib import core
from ai_overlay_lib.ai import provider_chain
from ai_overlay_lib.accounts import Usage

fails, passed = [], [0]


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  :: " + str(detail)) if detail and not cond else ""))
    if cond: passed[0] += 1
    else: fails.append(name)


def gem(name="Gemini", key="key-a", model="gemini-3.5-flash", **kw):
    return core.make_provider("Gemini", name=name, key=key, model=model, **kw)


def names(ps): return [p["name"] for p in ps]


# ---------- identity ----------
a, b, c = gem("Gemini A", "key-a"), gem("Gemini B", "key-b"), gem("Gemini C", "key-c")
check("every configuration gets a unique id", len({a["id"], b["id"], c["id"]}) == 3)
check("ids are not names or models", all(p["id"] not in (p["name"], p["model"]) for p in (a, b, c)))

# three configs with the SAME provider name and model but different keys stay distinct
d1, d2, d3 = gem("Gemini", "k1"), gem("Gemini", "k2"), gem("Gemini", "k3")
check("identical name/model/model entries stay separate", len({p["id"] for p in (d1, d2, d3)}) == 3)

# normalize keeps ids and does not merge duplicates
cfg = copy.deepcopy(core.DEFAULTS); cfg["providers"] = copy.deepcopy([d1, d2, d3])
core.normalize_providers(cfg)
check("normalization never merges duplicate configurations", len(cfg["providers"]) == 3 and names(cfg["providers"]) == ["Gemini"] * 3)
check("normalization keeps existing ids", [p["id"] for p in cfg["providers"]] == [d1["id"], d2["id"], d3["id"]])

# ---------- order ----------
check("request chain follows Groq-first display order",
      names(provider_chain([{"name": "Groq", "url": "https://api.groq.com/x", "model": "m", "key": "g"},
                            {"name": "Gemini", "url": "https://generativelanguage.googleapis.com/x", "model": "m", "key": "g"}])) == ["Groq", "Gemini"])
check("request chain follows Gemini-first display order",
      names(provider_chain([{"name": "Gemini", "url": "https://generativelanguage.googleapis.com/x", "model": "m", "key": "g"},
                            {"name": "Groq", "url": "https://api.groq.com/x", "model": "m", "key": "g"}])) == ["Gemini", "Groq"])
check("duplicate Gemini configs are all retained in order",
      [p["id"] for p in provider_chain([d1, d2, d3])] == [d1["id"], d2["id"], d3["id"]])

# quota/cooldown state must never reorder
tmp_u = os.path.join(tempfile.mkdtemp(), "usage.json")
u = Usage(tmp_u)
u.rec(d1); u.rec(d1); u.rec(d1)
check("an exhausted top provider is still attempted first", provider_chain([d1, d2], usage=u)[0]["id"] == d1["id"])
check("a 'cooling' top provider is still attempted first",
      provider_chain([d1, d2], cool={(d1["url"], d1["model"]): 9e12})[0]["id"] == d1["id"])

# only impossible entries are skipped
off = dict(d2, enabled=False)
nokey = dict(d3, key="")
check("disabled entries are skipped, others keep their order",
      [p["id"] for p in provider_chain([d1, off, nokey, d2])] == [d1["id"], d2["id"]])

# ---------- persistence / reordering / editing / removal ----------
tmpdir = tempfile.mkdtemp()
old_cfg, old_bundled = core.CFG_PATH, core.BUNDLED_CFG
core.CFG_PATH = os.path.join(tmpdir, "config.json"); core.BUNDLED_CFG = os.path.join(tmpdir, "missing.json")
try:
    cfg = copy.deepcopy(core.DEFAULTS); cfg["providers"] = copy.deepcopy([a, b, c])
    core.save_cfg(cfg)
    one = core.load_cfg()
    check("saved order survives restart", names(one["providers"]) == ["Gemini A", "Gemini B", "Gemini C"])
    ids1 = [p["id"] for p in one["providers"]]

    one["providers"] = [one["providers"][2], one["providers"][0], one["providers"][1]]
    core.save_cfg(one)
    two = core.load_cfg()
    check("reordered list is loaded in the new display order", names(two["providers"]) == ["Gemini C", "Gemini A", "Gemini B"])
    check("reordering preserves every id", [p["id"] for p in two["providers"]] == [ids1[2], ids1[0], ids1[1]])

    # edit exactly one configuration: name/model/key change, identity stays
    edited = copy.deepcopy(two)
    edited["providers"][1]["name"] = "Gemini A renamed"; edited["providers"][1]["key"] = "new-key"; edited["providers"][1]["model"] = "gemini-3-pro"
    core.save_cfg(edited)
    three = core.load_cfg()
    check("editing one config preserves its identity", three["providers"][1]["id"] == ids1[0])
    check("editing one config does not touch the others",
          [p["id"] for p in (three["providers"][0], three["providers"][2])] == [ids1[2], ids1[1]])

    # remove one: others and their order remain
    three["providers"].pop(1); core.save_cfg(three)
    four = core.load_cfg()
    check("removing one config leaves the rest intact", [p["id"] for p in four["providers"]] == [ids1[2], ids1[1]])

    # a config file with no ids is repaired once and stays stable across restarts
    raw = copy.deepcopy(core.DEFAULTS); raw["providers"] = [dict(a), dict(b)]; [p.pop("id", None) for p in raw["providers"]]
    json.dump(raw, open(core.CFG_PATH, "w"))
    repaired = core.load_cfg(); rid = [p["id"] for p in repaired["providers"]]
    again = core.load_cfg()
    check("missing ids are generated and persisted", rid == [p["id"] for p in again["providers"]] and len(set(rid)) == 2)
finally:
    core.CFG_PATH, core.BUNDLED_CFG = old_cfg, old_bundled

# ---------- exact Settings methods: move / edit ----------
from PyQt6.QtWidgets import QApplication
from ai_overlay_lib import dialogs
app = QApplication.instance() or QApplication([])

pd = dialogs.ProviderDialog(d1); pd.accept()
check("editing a provider through the dialog keeps its id", pd.result_p and pd.result_p["id"] == d1["id"])
pd2 = dialogs.ProviderDialog(); pd2.accept()
check("a newly added provider gets a fresh id", pd2.result_p and pd2.result_p["id"] not in (d1["id"], d2["id"], d3["id"]))


class FakeList:
    def __init__(s, row): s.row = row
    def currentRow(s): return s.row
    def setCurrentRow(s, row): s.row = row


class FakeSettings:
    def __init__(s, provs): s.provs = copy.deepcopy(provs); s.plist = FakeList(0); s.refreshed = []
    def k_collect(s): pass
    def p_refresh(s, sel=0): s.refreshed.append(sel); s.plist.setCurrentRow(sel)


fs = FakeSettings([d1, d2, d3])
dialogs.Settings.p_move(fs, 1)
check("moving a provider down updates the backend list immediately",
      names(fs.provs) == ["Gemini", "Gemini", "Gemini"] and [p["id"] for p in fs.provs] == [d2["id"], d1["id"], d3["id"]])
dialogs.Settings.p_move(fs, -1)
check("moving a provider up restores the exact order and ids",
      names(fs.provs) == ["Gemini", "Gemini", "Gemini"] and [p["id"] for p in fs.provs] == [d1["id"], d2["id"], d3["id"]])

# Edit through Settings.p_edit must preserve identity even if a dialog dropped it.
fs2 = FakeSettings([d1, d2, d3]); fs2.plist.row = 1
real_dialog = dialogs.ProviderDialog
class EditDialog:
    def __init__(s, p, parent=None): s.result_p = {"name": "Gemini B edited", "url": p["url"], "key": "new-b", "model": p["model"],
                                                    "extra": {}, "vision": True, "audio": True, "enabled": True, "daily_limit": 0}
    def exec(s): return True
try:
    dialogs.ProviderDialog = EditDialog
    dialogs.Settings.p_edit(fs2)
finally:
    dialogs.ProviderDialog = real_dialog
check("editing one row does not replace another or lose its id",
      fs2.provs[1]["id"] == d2["id"] and fs2.provs[1]["name"] == "Gemini B edited"
      and [fs2.provs[0]["id"], fs2.provs[2]["id"]] == [d1["id"], d3["id"]])

# ---------- usage isolation ----------
tmpu = os.path.join(tempfile.mkdtemp(), "usage.json")
us = Usage(tmpu)
A, B, C = d1, d2, d3
us.rec(A); us.tokens(A, {"prompt": 100, "output": 20, "thoughts": 5, "total": 125})
check("Gemini A usage increases after its request", us.left(A)[0] == 1)
check("Gemini B stays at zero after A", us.left(B)[0] == 0)
check("Gemini C stays at zero after A", us.left(C)[0] == 0)
check("tokens are attached only to A", us.d[A["id"]]["tok"] == {"prompt": 100, "output": 20, "thoughts": 5, "total": 125}
      and "tok" not in us.d.get(B["id"], {}) and "tok" not in us.d.get(C["id"], {}))

us.rec(B); us.tokens(B, {"prompt": 7, "output": 3, "thoughts": 0, "total": 10})
check("A remains unchanged after B", us.left(A)[0] == 1 and us.d[A["id"]]["tok"]["total"] == 125)
check("B records its own request and tokens", us.left(B)[0] == 1 and us.d[B["id"]]["tok"]["total"] == 10)

us.err(C, "503 high demand")
check("errors are counted only on C", us.d[C["id"]]["errors"] == 1 and us.d[A["id"]].get("errors", 0) == 0)
check("usage line shows per-config errors", "1 err" in us.line(C) and "err" not in us.line(B))

# restart
us2 = Usage(tmpu)
check("per-config usage survives restart", us2.left(A)[0] == 1 and us2.left(B)[0] == 1 and us2.left(C)[0] == 0)
check("per-config tokens survive restart", us2.d[A["id"]]["tok"]["total"] == 125 and us2.d[B["id"]]["tok"]["total"] == 10)
check("per-config errors survive restart", us2.d[C["id"]]["errors"] == 1)
check("usage keys are config ids, not names/models", all(k in (A["id"], B["id"], C["id"]) for k in us2.d))

# previous-day history stays attached to the same configuration
old_today = Usage.today
hp = os.path.join(tempfile.mkdtemp(), "usage.json")
try:
    Usage.today = staticmethod(lambda p: "2026-11-26")
    hu = Usage(hp); hu.rec(A); hu.tokens(A, {"prompt": 4, "total": 6}); hu.err(A, "503")
    Usage.today = staticmethod(lambda p: "2026-11-27")
    hu.rec(A)
    h = hu.d[A["id"]].get("history") or []
    check("daily history is kept per configuration", len(h) == 1 and h[0]["day"] == "2026-11-26" and h[0]["tok"]["total"] == 6, h)
finally:
    Usage.today = staticmethod(old_today)

# legacy migration: unique key moves; ambiguous duplicate key is left alone
legacy_path = os.path.join(tempfile.mkdtemp(), "usage.json")
json.dump({"Gemini|gemini-3.5-flash": {"day": us.today(A), "count": 9}}, open(legacy_path, "w"))
lu = Usage(legacy_path); lu.migrate([A])
check("a unique legacy counter migrates to the new id", lu.d.get(A["id"], {}).get("count") == 9)

legacy2 = os.path.join(tempfile.mkdtemp(), "usage.json")
json.dump({"Gemini|gemini-3.5-flash": {"day": us.today(A), "count": 9}}, open(legacy2, "w"))
lu2 = Usage(legacy2); lu2.migrate([A, B])
check("an ambiguous legacy counter is never assigned to the wrong config",
      lu2.d.get(A["id"]) is None and lu2.d.get(B["id"]) is None and lu2.d["Gemini|gemini-3.5-flash"]["count"] == 9)

print("\n%d PASS / %d FAIL" % (passed[0], len(fails)))
sys.exit(1 if fails else 0)
