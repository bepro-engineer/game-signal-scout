#!/bin/bash
# Game の論理 DB とロール gss を、共有の PostgreSQL（VAIO）に作る（docs/database.md の手順を 1 つにした台本。Mac mini で流す）。
#
# 秘密の扱い:
# - gss のパスワードは Mac mini で作り、runtime/db.env（Git の外・0600）にだけ置く。画面・引数・履歴・commit に出さない。
# - VAIO に送るのは SCRAM-SHA-256 の検証値だけ（元のパスワードには戻せない。PostgreSQL は検証値をそのまま受け取る）。
# - VAIO の sudo のパスワードは、本人が VAIO の端末で入れる（この台本は受け取らない・保存しない）。
#
# すること（VAIO、root）: 事前の確認（同名の DB・ロールがない、接続数、ディスク、pg_hba.d が読まれる）→ ロール gss・DB game_signal_scout →
#   PUBLIC の CONNECT を外す → pg_hba.d/game.conf（Mac mini から gss が game_signal_scout にだけ）→ reload → 権限の確認。
# 同名の DB かロールが既にあれば、何も変えずに止まる。戻し方は docs/database.md の「切り戻し」。
set -euo pipefail
cd "$(dirname "$0")/.."
SSH=${SSH:-vaio}
DBHOST=${DBHOST:-192.168.11.3}
MAC=${MAC:-192.168.11.8}
ENVF=runtime/db.env
[ -e "$ENVF" ] && { echo "runtime/db.env が既にある（上書きしない）。作り直すなら、切り戻しの後に消してから流す" >&2; exit 2; }
mkdir -p runtime
umask 077
# パスワードと検証値（標準ライブラリだけ。RFC 5802 / 7677、PostgreSQL と同じ 4096 回）
read -r PW VERIFIER < <(python3 - <<'PY'
import base64, hashlib, hmac, secrets
pw = secrets.token_urlsafe(32)
salt = secrets.token_bytes(16)
salted = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 4096)
ck = hmac.new(salted, b"Client Key", "sha256").digest()
sk = hmac.new(salted, b"Server Key", "sha256").digest()
b = lambda x: base64.b64encode(x).decode()
print(pw, f"SCRAM-SHA-256$4096:{b(salt)}${b(hashlib.sha256(ck).digest())}:{b(sk)}")
PY
)
REMOTE=$(mktemp)
trap 'rm -f "$REMOTE"' EXIT
cat > "$REMOTE" <<EOF
#!/bin/bash
set -euo pipefail
[ "\$(id -u)" = 0 ] || { echo "root で動かす（sudo bash）" >&2; exit 1; }
HBA_DIR=/etc/postgresql/18/main/pg_hba.d
q() { sudo -u postgres psql -X -v ON_ERROR_STOP=1 -Atc "\$1"; }
echo "== 事前の確認（読み取りだけ）"
[ -z "\$(q "SELECT datname FROM pg_database WHERE datname LIKE 'game_signal_scout%'")" ] || { echo "同名の DB がある。止める" >&2; exit 3; }
[ -z "\$(q "SELECT rolname FROM pg_roles WHERE rolname LIKE 'gss%'")" ] || { echo "同名のロールがある。止める" >&2; exit 3; }
echo "接続数: \$(q "SELECT count(*) || ' / ' || current_setting('max_connections') FROM pg_stat_activity")（Game は最大 9 を足す）"
df -h /var/lib/postgresql | tail -1
grep -Eq "^[[:space:]]*include_dir[[:space:]]+'?\$HBA_DIR'?|^[[:space:]]*include_dir[[:space:]]+'?pg_hba.d'?" /etc/postgresql/18/main/pg_hba.conf \
  || { echo "pg_hba.conf が pg_hba.d を読んでいない。止める（手で確かめる）" >&2; exit 4; }
ls "\$HBA_DIR"
[ ! -e "\$HBA_DIR/game.conf" ] || { echo "pg_hba.d/game.conf が既にある。止める" >&2; exit 3; }
echo "== 作る"
# 検証値は \$ を含むので、展開しないヒアドキュメントで psql に渡す（CREATE DATABASE は取引の中で動かないので 1 文ずつ）
sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE gss LOGIN PASSWORD '$VERIFIER';
CREATE DATABASE game_signal_scout OWNER gss;
REVOKE CONNECT ON DATABASE game_signal_scout FROM PUBLIC;
GRANT CONNECT ON DATABASE game_signal_scout TO gss;
SQL
printf '# Game Signal Scout（game-signal-scout の deploy/create-db.sh が置いた）: Mac mini から gss が game_signal_scout にだけ\nhost game_signal_scout gss $MAC/32 scram-sha-256\n' > "\$HBA_DIR/game.conf"
chown postgres:postgres "\$HBA_DIR/game.conf"; chmod 640 "\$HBA_DIR/game.conf"
systemctl reload postgresql@18-main
sleep 1
q "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL" | grep -qx 0 || { echo "pg_hba の読み込みに誤りがある（pg_hba_file_rules を見る）" >&2; exit 5; }
echo "== 権限の確認（gss が CONNECT できる DB）"
q "SELECT datname FROM pg_database WHERE datname NOT IN ('template0','template1') AND has_database_privilege('gss', datname, 'CONNECT') ORDER BY 1"
echo "== 完了"
EOF
echo "GSS_DB_DSN=postgresql://gss:${PW}@${DBHOST}:5432/game_signal_scout" > "$ENVF"
unset PW
chmod 600 "$ENVF"
scp -q "$REMOTE" "$SSH:gss-create-db.sh"
ssh -t "$SSH" 'chmod 600 ~/gss-create-db.sh; sudo bash ~/gss-create-db.sh; rc=$?; rm -f ~/gss-create-db.sh; exit $rc' || {
  rc=$?; echo "VAIO の作業が終了コード $rc で止まった。runtime/db.env を消す（VAIO の状態は上の出力で確かめる）" >&2; rm -f "$ENVF"; exit $rc; }
echo "VAIO の作業が終わった。続き: Mac mini で .venv/bin/alembic upgrade head など（docs/database.md）"
