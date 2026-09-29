"""Python / Streamlit プロジェクト向けの簡易セキュリティスキャナ（標準ライブラリのみ）。

使い方:
    python scan.py <プロジェクトのパス>

目的は「人間（Claude）が読む前の下見」。パターン一致なので誤検知も見逃しもある。
検出結果は必ずコードを読んで確認し、文脈に応じて重要度を判断すること。

秘密情報（APIキーなど）の値は出力しない。検出時も先頭4文字以外は伏せ字にする。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".claude", ".agents", ".venv", "venv", "env", "__pycache__", "node_modules", "site-packages",
             ".mypy_cache", ".pytest_cache", "dist", "build"}
TEXT_SUFFIXES = {".py", ".toml", ".json", ".yaml", ".yml", ".cfg", ".ini", ".txt", ".md", ".sh", ".ps1"}

# 秘密情報らしき文字列（値そのものは表示しない）
SECRET_PATTERNS = [
    ("Google APIキー", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Anthropic APIキー", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI APIキー", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("AWSアクセスキー", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHubトークン", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")),
    ("Slackトークン", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
# 変数への直書き: api_key = "xxxxxxxx"
HARDCODED = re.compile(
    r"""(?i)\b\w*(api_?key|secret|token|passw(or)?d)\w*\s*[:=]\s*["']([^"'\s]{8,})["']"""
)
PLACEHOLDER_WORDS = ("your", "xxx", "example", "dummy", "here", "placeholder", "changeme", "<", "...")

# (ルールID, 目安の重要度, 説明, 正規表現)
CODE_RULES = [
    ("html-unsafe", "中", "unsafe_allow_html=True（HTMLがそのまま描画される。ユーザー入力やLLM出力を渡すとXSS）",
     re.compile(r"unsafe_allow_html\s*=\s*True")),
    ("html-component", "中", "components.html / st.html（任意のHTML/JSを描画）",
     re.compile(r"components(\.v1)?\.html\(|\bst\.html\(")),
    ("code-eval", "高", "eval/exec（入力やLLM出力が届くと任意コード実行）",
     re.compile(r"(?<![\w.])(eval|exec)\s*\(")),
    ("code-pickle", "高", "pickle/marshal/joblib の読み込み（信頼できないデータで任意コード実行）",
     re.compile(r"\b(pickle|marshal|joblib|dill)\.loads?\(")),
    ("code-yaml", "中", "yaml.load（SafeLoader 以外は危険）",
     re.compile(r"\byaml\.load\((?![^)]*SafeLoader)")),
    ("shell", "高", "shell=True / os.system / os.popen（コマンドインジェクション）",
     re.compile(r"shell\s*=\s*True|\bos\.(system|popen)\(")),
    ("tls-off", "中", "verify=False（TLS証明書の検証を無効化）",
     re.compile(r"verify\s*=\s*False")),
    ("sql-format", "高", "SQL を文字列連結/f-string で組み立てている可能性（SQLインジェクション）",
     re.compile(r"""(?i)execute\(\s*f["']|execute\([^)]*(%|\.format\(|\+)""")),
    ("secret-display", "高", "環境変数/シークレットを画面やログに出している可能性",
     re.compile(r"(?i)(st\.(write|text|code|markdown|json|info|caption)|print|log(ging)?\.\w+)\([^)]*"
                r"(os\.environ|os\.getenv|st\.secrets|\bapi_key\b|\bsecret\b|\btoken\b|\bpassword\b)")),
    ("error-detail", "低", "例外の中身/トレースバックを画面に表示（公開時に内部情報が漏れる）",
     re.compile(r"st\.(exception|code|write|error|text)\([^)]*(str\(e\)|traceback|\be\))")),
    ("upload", "情報", "file_uploader（サイズ・種類・保存先パスを確認）",
     re.compile(r"file_uploader\(")),
    ("user-url", "情報", "外部URLへのリクエスト（ユーザー指定URLならSSRF、timeout 指定も確認）",
     re.compile(r"\b(requests|httpx|urllib\.request)\.(get|post|request|urlopen)\(")),
    ("cache-shared", "情報", "st.cache_data / st.cache_resource（全ユーザーで共有される。個人データを入れていないか確認）",
     re.compile(r"st\.cache_(data|resource)")),
    ("tempfile", "低", "tempfile.mktemp（競合状態。mkstemp/NamedTemporaryFile を使う）",
     re.compile(r"tempfile\.mktemp\(")),
]

CONFIG_RULES = [
    ("config-xsrf", "中", "enableXsrfProtection = false", re.compile(r"enableXsrfProtection\s*=\s*false")),
    ("config-cors", "低", "enableCORS = false", re.compile(r"enableCORS\s*=\s*false")),
    ("config-error", "低", "showErrorDetails が有効（公開時はトレースバックが見える）",
     re.compile(r"showErrorDetails\s*=\s*(true|\"full\"|\"stacktrace\")")),
    ("config-upload", "情報", "maxUploadSize の設定", re.compile(r"maxUploadSize\s*=")),
]


def mask(text: str) -> str:
    """行の中の秘密情報らしき部分を伏せ字にする。"""
    for _, pat in SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(0)[:4] + "****", text)
    text = HARDCODED.sub(lambda m: m.group(0).replace(m.group(3), m.group(3)[:4] + "****"), text)
    return text


def iter_files(root: Path):
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            yield p


def read(p: Path) -> list[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def is_env_file(p: Path) -> bool:
    return p.name == ".env" or (p.name.startswith(".env.") and p.name not in (".env.example", ".env.sample", ".env.template"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    shown_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    root = shown_root
    # Windows の 260 文字制限を超える深いパスでもファイルを見落とさないよう、長いパス形式にする
    if os.name == "nt" and not str(root).startswith("\\\\?\\"):
        root = Path("\\\\?\\" + str(root))
    findings: list[tuple[str, str, str, str]] = []  # (重要度, ルール, 場所, 内容)

    def add(sev, rule, loc, msg):
        findings.append((sev, rule, loc, msg))

    files = list(iter_files(root))
    rel = lambda p: str(p.relative_to(root)).replace("\\", "/")

    # --- 秘密情報ファイルと .gitignore
    gitignore = root / ".gitignore"
    ignore_lines = [l.strip() for l in read(gitignore)] if gitignore.exists() else []
    secret_files = [p for p in files if is_env_file(p) or p.name == "secrets.toml"]
    for p in secret_files:
        ignored = any(l in (p.name, rel(p), f"/{rel(p)}", ".env*", ".env.*", "*.env") or
                      (p.name == "secrets.toml" and ".streamlit" in l) for l in ignore_lines)
        add("情報" if ignored else "高", "secret-file", rel(p),
            f"秘密情報ファイルがあります（値は表示しません）。.gitignore: {'除外済み' if ignored else '未除外！'}")
    if not gitignore.exists():
        add("中", "gitignore", ".gitignore", ".gitignore がありません（.env や .streamlit/secrets.toml を除外する）")

    # --- git 管理下なら、追跡・履歴に秘密ファイルが入っていないか
    if (root / ".git").exists() and shutil.which("git"):
        def git(*args):
            r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            return r.stdout
        for line in git("ls-files").splitlines():
            name = line.rsplit("/", 1)[-1]
            if name == ".env" or name == "secrets.toml" or (name.startswith(".env.") and "example" not in name):
                add("高", "git-tracked-secret", line, "秘密情報ファイルが git で追跡されています")
        hist = git("log", "--all", "--name-only", "--pretty=format:", "--", ".env", "*.env", "**/secrets.toml")
        for name in sorted({l for l in hist.splitlines() if l.strip()}):
            add("高", "git-history-secret", name, "過去のコミット履歴に秘密情報ファイルがあります（キーの再発行が必要）")
    else:
        add("情報", "git", "-", "git リポジトリではないため、コミット履歴のチェックは省略しました")

    # --- ファイル内容
    for p in files:
        if p.suffix not in TEXT_SUFFIXES or is_env_file(p) or p.name == "secrets.toml":
            continue
        lines = read(p)
        is_py = p.suffix == ".py"
        for no, line in enumerate(lines, 1):
            loc = f"{rel(p)}:{no}"
            stripped = line.strip()
            for label, pat in SECRET_PATTERNS:
                if pat.search(line):
                    add("高", "secret-literal", loc, f"{label}らしき文字列: {mask(stripped)[:120]}")
            m = HARDCODED.search(line)
            if is_py and m and not any(w in m.group(3).lower() for w in PLACEHOLDER_WORDS):
                add("高", "secret-hardcoded", loc, f"秘密情報の直書きの可能性: {mask(stripped)[:120]}")
            if is_py and not stripped.startswith("#"):
                for rule, sev, desc, pat in CODE_RULES:
                    if pat.search(line):
                        add(sev, rule, loc, f"{desc}\n      > {mask(stripped)[:140]}")
            if p.suffix == ".toml" and ".streamlit" in rel(p):
                for rule, sev, desc, pat in CONFIG_RULES:
                    if pat.search(line):
                        add(sev, rule, loc, desc)

    # --- 依存関係
    req = root / "requirements.txt"
    if req.exists():
        deps = [l.strip() for l in read(req) if l.strip() and not l.startswith("#")]
        loose = [d for d in deps if "==" not in d]
        if loose:
            add("情報", "deps-unpinned", "requirements.txt",
                f"バージョン固定されていない依存: {', '.join(loose)}（再現性と脆弱版の混入に注意）")
    elif not (root / "pyproject.toml").exists():
        add("低", "deps-missing", "-", "requirements.txt / pyproject.toml が見つかりません")
    add("情報", "deps-audit", "-",
        "pip-audit が " + ("利用可能です: `pip-audit -r requirements.txt`" if shutil.which("pip-audit")
                         else "未インストールです（導入はユーザーに確認してから）"))

    # --- 出力
    order = {"高": 0, "中": 1, "低": 2, "情報": 3}
    findings.sort(key=lambda f: (order[f[0]], f[2]))
    print(f"# スキャン結果: {shown_root}")
    print(f"対象ファイル数: {len(files)} / 検出: {len(findings)} 件（パターン一致のため要確認）\n")
    for sev, rule, loc, msg in findings:
        print(f"[{sev}] {rule}  {loc}\n      {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
