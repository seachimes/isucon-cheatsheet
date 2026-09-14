# pprotein サーバの導入（Akamai / Ansible）

pprotein 本体（UI + 収集サーバ）を Akamai/Linode 上で Ansible により導入する。
インフラ（インスタンス・ファイアウォール・Cloudflare Tunnel/DNS/Access）と
**cloudflared の導入**は Terraform（`pprotein-infra`）が担当し、Ansible は
**ホスト内部の依存導入とアプリ配置**を担当する。

ライフサイクルが異なるため playbook を2つに分ける。

- `bootstrap.yml` … 初期構築。一度だけ実行する（OS 依存パッケージ）。
- `deploy.yml` … アプリの配置と更新。バージョンを上げたら繰り返し実行する。

- 競技用サーバ側の `pprotein-agent` は既存の [計測ツール導入](measurement-tools.md#pprotein-agent-の導入) を参照。
- 本ドキュメントは**pprotein サーバ（別ホスト）**の導入を扱う。

## 前提（Terraform 側で完了していること）

- Akamai/Linode のインスタンス + ファイアウォール（`pprotein-infra/terraform/akamai`）。
  - inbound は全遮断（`firewall_admin_cidr = ""`）。
  - **cloud-init**（インスタンスの `user_data`）が cloudflared を導入し、初回起動時に
    Cloudflare Tunnel を確立する。
- Cloudflare Tunnel / DNS / Access（`pprotein-infra/terraform/cloudflare`）。
  - ingress は `http://localhost:9000`（UI）と `ssh://localhost:22`（管理・デプロイ）。
- 配布物は **GitHub Release**（`seachimes/pprotein`、タグ `v*`）。

> **鶏卵の解消**: Tunnel は cloudflared が上げるもので、Tunnel SSH で Ansible を流すには
> 先に Tunnel が必要になる。そこで cloudflared は Ansible ではなく **cloud-init** が入れる。
> これにより初回から Tunnel SSH で接続でき、inbound を開ける必要がない。

トンネルトークンは Terraform の出力から取得し、`terraform/akamai` の tfvars に渡す。

```sh
terraform -chdir=pprotein-infra/terraform/cloudflare output -raw pprotein_tunnel_token
# -> pprotein-infra/terraform/akamai/terraform.tfvars の pprotein_tunnel_token に記入
```

> **Release が未公開の場合**、フォーク `seachimes/pprotein` で先にタグを打って公開する。
> `git tag v1.2.5 && git push origin v1.2.5`（goreleaser が
> `pprotein_1.2.5_linux_amd64.tar.gz` を作成する）。

## ディレクトリ構成

```
ansible/
├── ansible.cfg
├── hosts.example                                   # inventory のサンプル
├── pprotein-server/
│   ├── bootstrap.yml                               # 初期構築（一度だけ）
│   ├── deploy.yml                                  # 配置/更新（繰り返し）
│   └── vars.yml
└── templates/etc/systemd/system/
    └── pprotein.service.j2
```

cloudflared のユニットは `pprotein-infra/cloud-init/user-data-linode.yaml.tftpl` が生成する。

## 導入するもの

| コンポーネント | 役割 | 担当 | 備考 |
| --- | --- | --- | --- |
| cloudflared | ホスト常駐。UI(`:9000`) と SSH(`:22`) を Tunnel で公開 | cloud-init | `--token-file` でトークンを渡す |
| graphviz | pprof のグラフ描画（`dot`） | bootstrap | pprotein サーバ側で必要 |
| alp | nginx アクセスログ解析 | deploy | **サーバ側**で実行する |
| slp | MySQL スロークエリ解析 | deploy | **サーバ側**で実行する |
| pprotein | 本体（UI 埋め込み）。systemd で常駐 | deploy | `:9000` |

> `alp` / `slp` / `graphviz` は **pprotein サーバ側**が必要。
> agent（競技用サーバ）は生ログと pprof を出すだけで、これらは不要。

## 接続（Tunnel SSH）

inbound は全遮断のため、Ansible は Tunnel 経由で SSH する。cloud-init が
cloudflared を上げているので、初回からこの経路が使える。コントローラ側に
cloudflared と Access の **service token**（Terraform 出力）を用意する。

```sh
# 実行シェルで service token を export（argv に残さない）
export TUNNEL_SERVICE_TOKEN_ID="$(terraform -chdir=pprotein-infra/terraform/cloudflare output -raw access_service_token_client_id)"
export TUNNEL_SERVICE_TOKEN_SECRET="$(terraform -chdir=pprotein-infra/terraform/cloudflare output -raw access_service_token_client_secret)"
```

```sshconfig
# ~/.ssh/config
Host pprotein-ssh.example.com
  User root
  ProxyCommand cloudflared access ssh --hostname %h
```

`pprotein-ssh.example.com` は Terraform の `pprotein_ssh_hostname` 出力に合わせる。

```sh
terraform -chdir=pprotein-infra/terraform/cloudflare output -raw pprotein_ssh_hostname
```

inventory は `hosts.example` をコピーして対象ホストを書く（グループ `pprotein_server`）。

```ini
[pprotein_server]
pprotein ansible_host=pprotein-ssh.<your-zone> ansible_user=root
```

## 認証

Tunnel まわりの認証は3層に分かれている。

### 1. connector 認証（cloudflared → Cloudflare edge）

`pprotein_tunnel_token`（Terraform の `cloudflare_zero_trust_tunnel_cloudflared.pprotein` が発行）。
cloudflared はこのトークンで edge に接続し、トンネル `pprotein` に紐づく。
**このトークンを持つ者は誰でも connector を張れる**ため秘密扱い（state / cloud-init `user_data` に存在）。

### 2. Access 認証（クライアント → origin）

同じトンネルでもホスト名ごとに別の Access アプリ／ポリシーが付く（`pprotein-infra/terraform/cloudflare/main.tf`）。

| ホスト名 | アプリ | ポリシー | 認証方式 |
| --- | --- | --- | --- |
| `pprotein.<zone>`（UI） | pprotein UI | `allow-members` | **SSO**（`allowed_emails` の email を含む） |
| `pprotein-ssh.<zone>`（SSH） | pprotein SSH | `allow-deploy-service-token` | **service token**（`decision = non_identity`） |
| `agent-ssh.<zone>`（agent SSH） | pprotein-agent SSH | 同上 | service token |

- SSH は `non_identity` + `include { service_token = [deploy] }`。**`pprotein-deploy` service token
  （client id/secret）を持つ機械だけ**が通れる。
- これが `cloudflared access ssh` に渡す `TUNNEL_SERVICE_TOKEN_ID` / `TUNNEL_SERVICE_TOKEN_SECRET`。

### 3. SSH 認証（ssh → host）

Access 通過後は通常の SSH 鍵認証。`id_akamai`（インスタンスの `authorized_keys` に登録済み）で
`root` にログインする。

### Ansible の流れ

```
cloudflared access ssh（service token を提示）
  → Cloudflare Access が non_identity で許可
  → tunnel が ssh://localhost:22 へ転送（ingress）
  → sshd が id_akamai で鍵認証
```

つまり **service token（Access）と SSH 鍵（ホスト）の二段**。UI は SSO、SSH は service token。

## 実行

ライフサイクルで playbook を分けている。初回は bootstrap → deploy の順、以降の更新は deploy のみ。

```sh
cd ansible

# 1) 初期構築（一度だけ・OS 依存）
ansible-playbook -i hosts pprotein-server/bootstrap.yml \
  -e pprotein_server_hosts=pprotein_server

# 2) 配置/更新（バージョンを上げたら再実行）
ansible-playbook -i hosts pprotein-server/deploy.yml \
  -e pprotein_server_hosts=pprotein_server

# 除去（データは保持）
ansible-playbook -i hosts pprotein-server/deploy.yml \
  -e pprotein_server_hosts=pprotein_server \
  -e pprotein_server_state=absent
```

## playbook が行うこと

### bootstrap.yml（初回のみ）

1. **cloud-init の確認**: `cloudflared-pprotein` が `active` であることを確認
2. **依存導入**: `graphviz`、`curl`、`ca-certificates`

### deploy.yml（配置/更新）

3. **alp / slp**: 固定バージョンで `/usr/local/bin` へ導入
4. **pprotein**: Release から取得して `/usr/local/bin/pprotein` へ配置
5. **systemd**: `pprotein.service` を配置し、起動・自動起動を有効化
6. **data dir**: `/opt/pprotein/data` を作成

再実行が冪等になるよう、ダウンロードと展開は**バージョン付きの一時パス**に分離し、
バイナリが変化したときだけ systemd を再起動する（handler）。

## pprotein の取得

```sh
https://github.com/{{ pprotein_repo }}/releases/download/{{ pprotein_ver }}/pprotein_{{ pprotein_archive_ver }}_linux_{{ pprotein_arch }}.tar.gz
```

- アーカイブには `pprotein` / `pprotein-agent` が同梱される（`LICENSE` の有無はリリースによる）。
- サーバでは `pprotein` を使用する。

## 変数一覧

`pprotein-server/vars.yml` の既定値。`-e key=value` で上書きできる。

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `pprotein_server_state` | `present` | `present`（導入）/ `absent`（除去）。deploy.yml が使用 |
| `pprotein_repo` | `seachimes/pprotein` | 配布元（フォーク） |
| `pprotein_ver` | `v1.2.5` | 固定バージョン |
| `pprotein_archive_ver` | `{{ pprotein_ver \| regex_replace('^v', '') }}` | 資産名用（`v` なし） |
| `pprotein_arch` | `amd64` | アーキテクチャ |
| `pprotein_server_bin_path` | `/usr/local/bin/pprotein` | サーバのバイナリ |
| `pprotein_server_service_name` | `pprotein` | systemd サービス名 |
| `pprotein_server_service_path` | `/etc/systemd/system/pprotein.service` | systemd ユニット |
| `pprotein_server_port` | `9000` | listen ポート |
| `pprotein_server_work_dir` | `/opt/pprotein` | WorkingDirectory |
| `pprotein_server_data_dir` | `/opt/pprotein/data` | データディレクトリ |
| `pprotein_server_user` | `root` | サービスの実行ユーザー |
| `pprotein_server_group` | `root` | サービスの実行グループ |
| `pprotein_server_tmp_archive` | `/tmp/pprotein-{{ pprotein_ver }}.tar.gz` | tarball（一時） |
| `pprotein_server_extract_dir` | `/tmp/pprotein-{{ pprotein_ver }}` | 展開先（一時） |
| `alp_ver` | `v1.0.21` | measurement と揃える |
| `slp_ver` | `v0.2.1` | measurement と揃える |

cloudflared の変数（`cloudflared_ver` 等）は `pprotein-infra/terraform/akamai` 側にある。

## systemd ユニット（pprotein）

`templates/etc/systemd/system/pprotein.service.j2`:

```ini
[Unit]
Description=pprotein
Documentation=https://github.com/seachimes/pprotein
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/pprotein
Environment=PORT=9000
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/local/bin/pprotein
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

cloudflared のユニットは cloud-init が生成する（`pprotein-infra/cloud-init/user-data-linode.yaml.tftpl`）。

- ingress（`http://localhost:9000` / `ssh://localhost:22`）は Terraform（Cloudflare 側）で定義済み。
- トークンは `--token-file` で読み、argv やログに残さない。

## agent 側（既存 playbook）

`measurement/pprotein-agent.yml` は配布元を **`seachimes/pprotein`**、バージョンを
**`v1.2.5`** に更新済み（サーバ側と揃える）。アーカイブ名の規則は同じ
（`pprotein_<ver>_linux_<arch>.tar.gz`）。

## 検証

- [ ] `systemctl status cloudflared-pprotein`（cloud-init 管理）が `active`
- [ ] `systemctl status pprotein` が `active (running)`
- [ ] `curl -s localhost:9000` が応答（UI）
- [ ] `which alp slp dot` が通る
- [ ] Cloudflare Tunnel が Healthy、UI が Access 経由で表示
- [ ] agent を targets に登録し `group/collect` が `ok`
- [ ] `bootstrap.yml` / `deploy.yml` を再実行しても差分が出ない（冪等）

## 注意

- 既存インスタンスに cloud-init の残骸（Docker 等）がある場合や、cloud-init
  （`user_data`）を変更した場合は、Terraform で**作り直してから** Ansible を適用する。
  ```sh
  terraform -chdir=pprotein-infra/terraform/akamai apply -replace=linode_instance.pprotein
  ```
  インスタンスは破壊・再作成され、`/opt/pprotein/data` などホスト上のデータは消える。
- cloud-init は `user_data` の変更を既存インスタンスへ再適用しない。変更時は
  インスタンスを作り直すか `cloud-init clean` 後に再実行する。
- トンネルトークンは Terraform state と Linode の `user_data` に載る。
  `pprotein-infra` は Private 前提。Ansible はトークンを扱わない。
- `alp` / `slp` は `@latest` を避けて固定する。
- pprotein サーバは単一ライター（bbolt）。複数プロセスで起動しない。
- 競技用サーバ（agent）とは別ホスト。混同しないこと。
