# 計測ツール導入（alp / slp / ログローテーション）

private-isu で行った計測ツールの導入を、任意の ISUCON 環境で使えるようプレースホルダ化して移植したもの。
Ansible の独立 playbook として実行する。`playbooks.yml` からは import しない（計測時だけ手動で流す）。

## 導入するツール

| ツール | 役割 | 前提 |
| --- | --- | --- |
| [alp](https://github.com/tkuchiki/alp) | nginx のアクセスログ（LTSV）を解析し、URI ごとの本数・レスポンスタイム・ボトルネックを可視化する | nginx の `access_log` を LTSV 形式にする |
| [slp](https://github.com/tkuchiki/slp) | MySQL のスロークエリログを解析し、重いクエリを可視化する | MySQL のスロークエリログを有効化する |
| [pprotein-agent](https://github.com/seachimes/pprotein) | nginx / MySQL のログや pprof を pprotein サーバへ提供するエージェント | alp / slp 相当のログ設定（LTSV・スロークエリログ） |
| rotate-measure-logs.sh | ベンチ前後に計測ログを退避し、計測区間ごとのログを分離する | alp / slp を導入済みであること |

## ディレクトリ構成

```
ansible/
├── ansible.cfg
├── inventories/                          # 環境ごとの inventory（hosts は gitignore）
│   ├── pprotein_server/hosts             # 共有サーバ（全環境共通）
│   ├── private-isu/hosts                 # 競技環境（[app] / [bench]）
│   └── examples/                         # 例（-i 対象外。コピーして使う）
│       ├── pprotein_server.hosts
│       ├── private-isu.hosts
│       ├── isucon14.hosts
│       └── isucon2026.hosts
├── envs/                                 # 環境プロファイル（環境差分の変数）
│   ├── private-isu.yml
│   ├── isucon14.yml
│   └── isucon2026.yml
├── measurement/
│   ├── vars.yml                          # プラットフォーム既定値
│   ├── alp.yml                           # alp の導入/除去
│   ├── slp.yml                           # slp の導入/除去
│   ├── pprotein-agent.yml                # pprotein-agent の導入/除去
│   ├── cloudflared-agent.yml             # 競技サーバの cloudflared（agent トンネル）
│   └── rotate.yml                        # ローテーションスクリプトの配置/削除
├── pprotein-server/                      # 計測サーバ（全環境で共有）
│   ├── bootstrap.yml
│   ├── deploy.yml
│   └── vars.yml
├── secrets.example.yml                   # secret のサンプル（secrets.yml は gitignore）
├── files/
│   └── etc/nginx/conf.d/log_format.conf          # LTSV の log_format
└── templates/
    ├── etc/nginx/sites-available/isucon.measure.conf.j2   # 計測用 site conf
    ├── etc/mysql/mysql.conf.d/zz-slowlog.cnf.j2           # スロークエリ設定
    ├── etc/systemd/system/pprotein-agent.service.j2       # pprotein-agent の unit
    ├── etc/systemd/system/cloudflared-agent.service.j2    # 競技サーバの cloudflared
    ├── etc/systemd/system/cloudflared-access-agent.service.j2  # サーバ側 access tcp
    ├── etc/systemd/system/pprotein.service.j2             # pprotein サーバの unit
    └── usr/local/bin/rotate-measure-logs.sh.j2            # ローテーション
```

## 事前準備

計測基盤は環境非依存。**pprotein サーバ1台を全環境で共有**し、競技環境だけを
inventory と環境プロファイルで差し替える（[measurement-architecture.md](measurement-architecture.md#環境の差し替え)）。

1. 使う環境の inventory とプロファイルを用意する。

   ```sh
   cd ansible
   cp inventories/examples/pprotein_server.hosts inventories/pprotein_server/hosts   # 共有サーバ（一度だけ）
   cp inventories/examples/private-isu.hosts        inventories/private-isu/hosts
   ```

   対象ホスト（`[app]` / `[bench]`）を `inventories/<env>/hosts` に書く。

2. 環境差分（nginx サイト名・公開ディレクトリ・ログパス・git リポジトリ）は
   `envs/<env>.yml` に書く。プラットフォーム既定は `measurement/vars.yml`。
   主な変数は [変数一覧](#変数一覧) を参照。

3. Ansible 実行前に SSH 疎通を確認する。

   ```sh
   ansible -i inventories/private-isu app -m ping
   ```

## alp の導入

### 手順

```sh
cd ansible
ansible-playbook -i inventories/private-isu measurement/alp.yml -e measure_hosts=app -e @envs/private-isu.yml
```

この playbook は以下を行う。

1. 既存の site conf（`nginx_site_path`）を `nginx_site_backup`（既定 `*.measure.orig`）へ退避（初回のみ）
2. `log_format ltsv` を `conf.d/log_format.conf` に配置
3. site conf を計測用テンプレートで置き換え、`access_log ... ltsv` を有効化
4. `nginx -t` で検証して `systemctl reload nginx`
5. `alp` バイナリをダウンロードして `/usr/local/bin` へ配置

> site conf は**丸ごと差し替わる**。計測用テンプレートは全リクエストをアプリ（`app_port`）へ
> プロキシする。静的配信の location など元設定の差分はテンプレートを編集して再現する。

### 使い方

```sh
# URI ごとの合計レスポンスタイム順に上位 30 件
alp ltsv --file /var/log/nginx/access.log \
  --sort sum -r \
  --output count,method,uri,min,max,sum,avg,p95 \
  --limit 30

# パスパラメータをまとめてルート単位で集計する
alp ltsv --file /var/log/nginx/access.log \
  --matching-groups '/diary/entry/.+','/image/.+' \
  --sort sum -r --limit 30

# 特定の URI だけを見る
alp ltsv --file /var/log/nginx/access.log \
  --filters 'Uri matches "^/posts"' \
  --sort sum -r --limit 30
```

主なオプション:

- `--sort` … `count` / `sum` / `avg` / `max` / `min` / `p90` / `p95` / `p99` / `stddev` など
- `-r, --reverse` … 降順ソート
- `-o, --output` … 表示列をカンマ区切りで指定
- `-m, --matching-groups` … URI を正規表現でグルーピング
- `-f, --filters` … `Uri` / `Method` / `Status` / `ResponseTime` などで絞り込み
- `-q, --query-string` … クエリ文字列まで含めて集計
- `--pos=FILE` … 読み取り位置を保存し、追記分だけを解析（ベンチ反復で便利）

## slp の導入

### 手順

```sh
cd ansible
ansible-playbook -i inventories/private-isu measurement/slp.yml -e measure_hosts=app -e @envs/private-isu.yml
```

この playbook は以下を行う。

1. スロークエリ設定（`zz-slowlog.cnf`）を配置
2. MySQL を再起動して設定を反映
3. `slp` バイナリをダウンロードして `/usr/local/bin` へ配置

既定の設定値:

- `slow_query_log = 1`
- `long_query_time = 0.05`
- `log_queries_not_using_indexes = 1`（`log_throttle_queries_not_using_indexes = 20`）

### 使い方

```sh
# 重いクエリを合計クエリタイム順に上位 30 件
slp my --file /var/log/mysql/mysql-slow.log \
  --sort sum-query-time -r \
  --output count,query,min-query-time,max-query-time,sum-query-time,avg-query-time \
  --limit 30

# 特定テーブル/パターンで絞り込む
slp my --file /var/log/mysql/mysql-slow.log \
  --filters 'Query matches "posts"' \
  --sort sum-query-time -r --limit 30

# 表示できる出力列の一覧
slp my print-output-options
```

主なオプション:

- `my` … MySQL のスロークエリログを解析（PostgreSQL は `pg`）
- `--sort` … `count` / `sum-query-time` / `avg-query-time` / `max-query-time` など
- `-o, --output` … 表示列をカンマ区切りで指定
- `-m, --matching-groups` … クエリを正規表現でグルーピング
- `-f, --filters` … `Query` / `QueryTime` / `RowsExamined` などで絞り込み
- `--pos=FILE` … 追記分だけを解析

## pprotein-agent の導入

競技用サーバに常駐させ、nginx / MySQL のログや pprof を pprotein サーバから
収集できるようにする。pprotein 本体（サーバ）は別ホスト（Linode）に置き、
**ISUCON のポリシー上 EC2 の inbound を開けられないため agent トンネルで接続**する。

> 配布元はフォークの [seachimes/pprotein](https://github.com/seachimes/pprotein)（`v1.2.5`）。
> `pprotein-agent.yml` は配布元とバージョンをサーバ側と揃えてある。
> サーバ側の収集経路は [pprotein-server.md](pprotein-server.md) を参照。

### 手順

```sh
cd ansible

# 1) 競技サーバの cloudflared（agent トンネル接続・一度だけ）
ansible-playbook -i inventories/private-isu measurement/cloudflared-agent.yml \
  -e measure_hosts=app -e @envs/private-isu.yml

# 2) pprotein-agent 本体
ansible-playbook -i inventories/private-isu measurement/pprotein-agent.yml \
  -e measure_hosts=app -e @envs/private-isu.yml
```

- `cloudflared-agent.yml` は **ホストごとの** `agent_tunnel_token`（`pprotein-infra` の
  `agent_hosts` に対応）を使い、**outbound のみ**で Cloudflare に接続する。
  トークンは `secrets.yml`（gitignore 済み）に `pprotein_agent_tunnel_tokens`（ラベル→トークン）
  として置き、inventory の `pprotein_agent_label` で選ぶ。
- `pprotein-agent.yml` は以下を行う。

1. `pprotein-agent` バイナリをダウンロードして `/usr/local/bin` へ配置
2. `pprotein-agent.service`（systemd ユニット）を配置
3. サービスを起動し、自動起動を有効化

> **同梱 agent との衝突**: ISUCON のイメージには pprotein が同梱されていることがある
> （例: isucon14 の `isucon-pprotein-agent.service` が `127.0.0.1:19000` を使用）。
> そのままだと `pprotein-agent` が `bind: address already in use` で再起動ループになる。
> 同梱を使わず fork を使うなら、先に `systemctl disable --now isucon-pprotein-agent` する。

### 設定

systemd ユニットは次の環境変数を設定する。いずれも `measurement/vars.yml` で変更できる。

- `PORT` … エージェントが listen するポート（`pprotein_agent_port`、既定 `19000`）
- `PPROTEIN_HTTPLOG` … nginx のアクセスログ（`nginx_access_log`）
- `PPROTEIN_SLOWLOG` … MySQL のスロークエリログ（`mysql_slowlog_file`）
- `PPROTEIN_GIT_REPOSITORY` … ソース表示に使う git リポジトリ（`pprotein_git_repository`）

エージェントはログファイルを読むため `pprotein_agent_user`（既定 `root`）で動かす。

### 使い方

collector は agent hostname を直接取得する。targets は **ホストごとの agent hostname** を参照する。

```json
[
  { "Type": "httplog", "Label": "nginx-1", "URL": "https://pprotein-agent-1.<zone>/debug/log/httplog", "Duration": 60 },
  { "Type": "slowlog", "Label": "mysql-1", "URL": "https://pprotein-agent-1.<zone>/debug/log/slowlog", "Duration": 60 },
  { "Type": "pprof",   "Label": "app-1",   "URL": "https://pprotein-agent-1.<zone>/debug/pprof/profile", "Duration": 60 }
]
```

経路:

```
pprotein サーバ（collector）
  → https://pprotein-agent-<label>.<zone>/debug/...（Access: bypass + サーバ IP 許可）
  → Cloudflare Edge → pprotein-agent-<label> トンネル
  → EC2 の cloudflared-agent（outbound）→ localhost:19000（pprotein-agent）
```

EC2 の inbound は不要。サーバ側は固定の `pprotein-agent-<label>.<zone>` を見るだけなので、
環境を差し替えてもサーバ側の変更は不要（EC2 側に connector を入れるだけ）。

> `/debug/log/httplog` は **tail ハンドラ**で、既定で「リクエスト後 30 秒間の新着行」を返す。
> 単発の `curl` で 0 バイトでも異常ではない（その間にログが増えれば返る）。

エージェントが公開するエンドポイント:

- `/debug/log/httplog` … nginx アクセスログ（LTSV）
- `/debug/log/slowlog` … MySQL スロークエリログ
- `/debug/fgprof`, `/debug/pprof/*` … プロファイリング

> アプリ本体の pprof を収集するには、アプリ側に pprotein の integration ライブラリを組み込むか、
> `standalone.Integrate(":19000")` をアプリ内で起動する。エージェント単体で取れるのはログのみ。

## ログローテーション

ベンチ実行の直前にスクリプトを実行すると、その時点までのログが退避され、
今回のベンチ分だけを alp / slp で解析できる。

### 手順

```sh
cd ansible
ansible-playbook -i inventories/private-isu measurement/rotate.yml -e measure_hosts=app -e @envs/private-isu.yml
```

### 使い方

```sh
# ベンチの直前に実行
ssh isu-app 'sudo /usr/local/bin/rotate-measure-logs.sh'

# ベンチ実行後、今回分だけを解析
ssh isu-app 'sudo alp ltsv --file /var/log/nginx/access.log --sort sum -r --limit 30'
ssh isu-app 'sudo slp my --file /var/log/mysql/mysql-slow.log --sort sum-query-time -r --limit 30'

# 前回分は連番で残る
ls -l /var/log/nginx/access.log.*
ls -l /var/log/mysql/mysql-slow.log.*
```

スクリプトは以下を行う。

1. `access.log` を空いている連番 `access.log.N` へ `mv`
2. `nginx -s reopen` でログファイルを開き直す
3. `mysql-slow.log` を `mysql-slow.log.N` へ `mv`
4. `SET GLOBAL slow_query_log=OFF/ON` でログファイルを開き直す

## 除去

各 playbook に `-e measure_state=absent` を渡すと導入前の状態へ戻す。

```sh
cd ansible
ansible-playbook -i inventories/private-isu measurement/alp.yml           -e measure_hosts=app -e @envs/private-isu.yml -e measure_state=absent
ansible-playbook -i inventories/private-isu measurement/slp.yml           -e measure_hosts=app -e @envs/private-isu.yml -e measure_state=absent
ansible-playbook -i inventories/private-isu measurement/pprotein-agent.yml -e measure_hosts=app -e @envs/private-isu.yml -e measure_state=absent
ansible-playbook -i inventories/private-isu measurement/rotate.yml        -e measure_hosts=app -e @envs/private-isu.yml -e measure_state=absent
```

- alp: 計測用 site conf をバックアップから復元（バックアップが無ければ削除）、`log_format.conf` と `alp` を削除
- slp: `zz-slowlog.cnf` と `slp` を削除し、MySQL を再起動
- pprotein-agent: サービスを停止・無効化し、ユニットとバイナリを削除
- rotate: `rotate-measure-logs.sh` を削除

## 変数一覧

`measurement/vars.yml` の**プラットフォーム既定値**。環境差分は `envs/<env>.yml` に
書いて `-e @envs/<env>.yml` で上書きする（[環境の差し替え](measurement-architecture.md#環境の差し替え)）。
`-e key=value` でも上書きできる。

| 変数 | 既定値 | 説明 | 環境差分の例 |
| --- | --- | --- | --- |
| `measure_state` | `present` | `present`（導入）/ `absent`（除去） | |
| `measure_arch` | `amd64` | バイナリのアーキテクチャ | |
| `nginx_conf_dir` | `/etc/nginx` | nginx の設定ディレクトリ | |
| `nginx_log_format_path` | `/etc/nginx/conf.d/log_format.conf` | LTSV の log_format 配置先 | |
| `nginx_site_name` | `isucon` | 対象サイト設定名（拡張子なし） | private-isu: `isucon` / isucon14: `isuride` |
| `nginx_site_path` | `/etc/nginx/sites-available/isucon.conf` | 対象サイト設定 | |
| `nginx_site_backup` | `<site_path>.measure.orig` | 元設定の退避先 | |
| `nginx_access_log` | `/var/log/nginx/access.log` | アクセスログ | |
| `nginx_listen` | `80` | listen ポート | |
| `client_max_body_size` | `10m` | アップロード上限 | |
| `app_public_dir` | `/home/isucon/webapp/public/` | 静的ファイルのルート | private-isu: `/home/isucon/private_isu/webapp/public/` |
| `app_port` | `8080` | アプリの待ち受けポート | |
| `mysql_conf_dir` | `/etc/mysql/mysql.conf.d` | MySQL 設定ディレクトリ | |
| `mysql_slowlog_conf` | `.../zz-slowlog.cnf` | スロークエリ設定 | |
| `mysql_slowlog_file` | `/var/log/mysql/mysql-slow.log` | スロークエリログ | |
| `mysql_slowlog_long_query_time` | `0.05` | 記録する閾値（秒） | |
| `mysql_service_name` | `mysql` | MySQL のサービス名 | |
| `rotate_script_path` | `/usr/local/bin/rotate-measure-logs.sh` | ローテーションスクリプト | |
| `pprotein_agent_path` | `/usr/local/bin/pprotein-agent` | エージェントのバイナリ | |
| `pprotein_agent_service_name` | `pprotein-agent` | systemd サービス名 | |
| `pprotein_agent_service_path` | `/etc/systemd/system/pprotein-agent.service` | systemd ユニット | |
| `pprotein_agent_port` | `19000` | エージェントの listen ポート | |
| `pprotein_agent_user` | `root` | サービスの実行ユーザ | |
| `pprotein_work_dir` | `/home/isucon` | 作業ディレクトリ | |
| `pprotein_git_repository` | `/home/isucon` | ソース表示に使う git リポジトリ | private-isu: `/home/isucon/private_isu` / isucon14: `/home/isucon/webapp` |
| `pprotein_extract_dir` | `/tmp/pprotein` | tarball の展開先（一時） | |
| `alp_ver` | `v1.0.21` | alp のバージョン（alp.yml 内） | |
| `slp_ver` | `v0.2.1` | slp のバージョン（slp.yml 内） | |
| `pprotein_ver` | `v1.2.5` | pprotein のバージョン（pprotein-agent.yml 内）。配布元は `seachimes/pprotein` | |

## 注意

- `measure_hosts` は必須。指定しないと inventory の対象グループが解決できずエラーになる。
- alp 導入時、site conf は丸ごと置き換わる。静的配信や別 location がある場合は
  `templates/etc/nginx/sites-available/isucon.measure.conf.j2` を環境に合わせて編集する。
- slp 導入・除去では MySQL を再起動する。接続断が許容されるタイミングで実行する。
- スロークエリログはディスクを消費する。計測後は `measure_state=absent` で戻すか、
  ログを退避して削除する。
- pprotein-agent は既定で `root` として動作し、`19000` 番で listen する。外部に公開せず、
  pprotein サーバからの SSH ポートフォワーディング経由でアクセスする。
- ログをローテーションすると、エージェントが追従しているファイル（inode）が変わる。
  収集前に `rotate-measure-logs.sh` を実行する運用と相性がよい。
