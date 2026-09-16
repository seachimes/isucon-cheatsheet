# 計測基盤の全体像（pprotein）

リリース戦略と、pprotein サーバ・エージェント・EC2・VPC の関係をまとめる。
個別の導入手順は [pprotein-server.md](pprotein-server.md) / [measurement-tools.md](measurement-tools.md) を参照。

計測基盤は**環境非依存**に作る。**pprotein サーバは1台を全環境で使い回し**、競技環境
（private-isu / isucon14 / isucon2026 …）だけを差し替える。同時に試行しないため、
サーバは1台で足りる。切り替えは inventory と環境プロファイルの差し替えで行う
（[環境の差し替え](#環境の差し替え)）。

## リリース戦略

配布元はフォークの [`seachimes/pprotein`](https://github.com/seachimes/pprotein)。

```
git tag v1.2.5 && git push origin v1.2.5
        │  (.github/workflows/publish-release.yml: tags v*)
        ▼
GitHub Actions → goreleaser
        │
        ▼
GitHub Release
  pprotein_1.2.5_linux_amd64.tar.gz   ← pprotein + pprotein-agent を同梱
  （darwin/arm64 なども同時に生成）
```

- タグ `v*` の push で GitHub Actions が goreleaser を実行し、**単一アーカイブに
  `pprotein` と `pprotein-agent` の両方**を同梱して Release に添付する。
- サーバは `pprotein`、競技用サーバは `pprotein-agent` と、**同じ Release を使う**。
- checksum は無効。Ansible は**バージョン付きの一時パス**で冪等性を担保する。
- バージョンは Ansible 変数 `pprotein_ver`（サーバ: `pprotein-server/vars.yml`、
  エージェント: `measurement/pprotein-agent.yml`）で固定する。

## 全体図

```mermaid
flowchart TB
  subgraph repo["pprotein リポジトリ (seachimes/pprotein)"]
    tag["git tag v*"] --> gha["GitHub Actions<br/>goreleaser"]
    gha --> rel["GitHub Release<br/>pprotein_VER_linux_amd64.tar.gz<br/>pprotein + pprotein-agent"]
  end

  subgraph ctrl["ローカル（運用端末）"]
    ansible["Ansible<br/>cloudflared access ssh"]
    browser["ブラウザ"]
  end

  subgraph cf["Cloudflare"]
    edge["Cloudflare Edge / DNS"]
    access["Access<br/>UI=SSO / SSH=service token"]
  end

  subgraph linode["Akamai/Linode: pprotein サーバ"]
    cfds["cloudflared<br/>(cloud-init)"]
    ppro["pprotein :9000<br/>alp / slp / graphviz"]
  end

  subgraph aws["AWS VPC（競技環境・例: private-isu）"]
    igw["Internet Gateway"]
    subgraph subnet["public subnet"]
      app["EC2: 競技用サーバ<br/>pprotein-agent :19000"]
      bench["EC2: ベンチマーカー"]
    end
  end

  rel -. "Ansible deploy.yml" .-> ppro
  rel -. "Ansible pprotein-agent.yml" .-> app

  browser -->|"HTTPS (SSO)"| edge
  ansible -->|"Tunnel SSH<br/>service token + SSH key"| edge
  edge --> access --> cfds
  cfds --- ppro

  ppro -->|"収集: cloudflared access tcp<br/>(pprotein-agent トンネル経由)"| app
  subnet --- igw
```

### テキスト版

```
[pprotein repo]  git tag v* ──> GitHub Actions (goreleaser) ──> GitHub Release
                                                              pprotein_<ver>_linux_amd64.tar.gz
                                                              (pprotein + pprotein-agent)
                                                                   │
                      ┌────────────────────────────────────────────┴───────────────┐
                      │ Ansible deploy.yml                                         │ Ansible pprotein-agent.yml
                      ▼                                                            ▼
        ┌─────────────────────────────┐       収集(HTTP)        ┌───────────────────────────────────┐
        │ Akamai/Linode               │  SSH port-forward /     │ AWS VPC (public subnet)           │
        │  pprotein サーバ            │  agent tunnel           │  ┌───────────────┐ ┌────────────┐ │
        │   pprotein :9000            │ ──────────────────────> │  │ EC2 app       │ │ EC2 bench  │ │
        │   alp / slp / graphviz      │                         │  │ pprotein-agent│ │            │ │
        │   cloudflared (cloud-init)  │                         │  │  :19000       │ │            │ │
        └──────────────┬──────────────┘                         │  └───────────────┘ └────────────┘ │
                       │                                        │        Internet Gateway           │
                       │                                        └───────────────────────────────────┘
                       │
              Cloudflare Edge / Access
                       │
        ┌──────────────┴───────────────┐
        │ ブラウザ (SSO)               │  ローカル Ansible (Tunnel SSH: service token + SSH key)
        └──────────────────────────────┘
```

## サーバ / エージェントの役割

| コンポーネント | ホスト | ポート | 役割 | 導入 |
| --- | --- | --- | --- | --- |
| pprotein（サーバ） | Linode（Akamai） | 9000 | UI + 収集サーバ。alp/slp/graphviz で解析 | `pprotein-server/deploy.yml` |
| cloudflared（サーバ） | Linode | — | Tunnel で UI/SSH を公開 | cloud-init（`pprotein-infra`） |
| cloudflared-access（サーバ） | Linode | 19001 | agent トンネルへ Access 経由で転送 | `pprotein-server/bootstrap.yml` |
| pprotein-agent | EC2（競技用サーバ） | 19000 | nginx/MySQL ログ・pprof を提供 | `measurement/pprotein-agent.yml` |
| cloudflared-agent | EC2（競技用サーバ） | — | agent を outbound でトンネル接続 | `measurement/cloudflared-agent.yml` |
| ベンチマーカー | EC2 | — | 負荷生成（計測対象外） | 環境ごと（例: private-isu provisioning） |

- エージェントは競技用サーバに**同居**し、ログファイルを読むため `root` で動く。
- サーバ側の `alp` / `slp` / `graphviz` は**サーバ側**で実行する（agent には不要）。

## 環境の差し替え

環境は2つの部品で表現する。詳細は [ansible/README.md](../ansible/README.md)。

| 部品 | 場所 | 内容 |
| --- | --- | --- |
| 共有サーバ | `ansible/inventories/pprotein_server/hosts` | pprotein サーバ（Tunnel SSH）。全環境共通 |
| 競技環境 | `ansible/inventories/<env>/hosts` | 競技用サーバ（`[app]` / `[bench]`） |
| 環境プロファイル | `ansible/envs/<env>.yml` | nginx サイト名・公開ディレクトリ・ログパス・git リポジトリなど |

```sh
# private-isu に向ける
ansible-playbook -i inventories/private-isu measurement/pprotein-agent.yml \
  -e measure_hosts=app -e @envs/private-isu.yml

# isucon14 に向ける（サーバはそのまま）
ansible-playbook -i inventories/isucon14 measurement/pprotein-agent.yml \
  -e measure_hosts=app -e @envs/isucon14.yml
```

- サーバ側（`pprotein-server/*`）は**全環境で共通**。環境ごとに触らない。
- 収集先（targets）は、その環境のエージェントを pprotein サーバに登録して切り替える。
- `hosts` は環境固有なので gitignore 済み。`inventories/examples/` をコピーして使う。

## EC2 / VPC（競技環境の例）

競技環境の構成は環境ごとに異なる。ここでは private-isu を例に示す
（CloudFormation `provisioning/cf.yaml`）。

- `VPC` + `public subnet` + `Internet Gateway` + `RouteTable`（0.0.0.0/0 → IGW）
- `ServerInstance`（競技用サーバ = エージェント同居）と `BenchmarkerInstance` の2台
- それぞれ `EIP`（固定グローバル IP）と `SecurityGroup`

isucon14 / isucon2026 なども同様に、競技用サーバ（エージェント同居）とベンチマーカーが
あれば、inventory と環境プロファイルを差し替えるだけで計測基盤を適用できる。

pprotein サーバは別クラウド（Linode）にあり、**ISUCON のポリシー上 EC2 の inbound は
開けられない**。そのため収集経路は **agent トンネル**（outbound のみ）で作る。

- Terraform（`pprotein-infra`）が **ホストごとに** agent トンネルを作成する
  （`agent_hosts = ["1","2","3"]` → `pprotein-agent-1/2/3.<zone>`）。
  1トンネルに複数 connector を張ると Cloudflare がラウンドロビンするため、
  ホストごとにトンネルを分ける。
- 競技用サーバ（EC2）: `measurement/cloudflared-agent.yml` が cloudflared を導入し、
  自分のトンネルの `agent_tunnel_token` で **outbound 接続**する（inbound 不要）。
  inventory の `pprotein_agent_label` でトークンを選ぶ。
- pprotein サーバ（Linode）: collector が **agent hostname を直接取得**する
  （`https://pprotein-agent-<label>.<zone>/debug/...`）。
- Access は **`bypass` + IP 許可**（サーバの egress IPv4/IPv6）。`Allow` + IP は
  identity ログインに飛ばされるため機械アクセスには使えない。

```
[pprotein サーバ]                                          [競技用サーバ (EC2)]
targets → https://pprotein-agent-<label>.<zone>/debug/...    pprotein-agent :19000
   │  （Access: bypass + サーバ IP 許可）                      ↑ localhost
   └── Cloudflare Edge ── pprotein-agent-<label> トンネル ── cloudflared-agent（outbound）
```

これにより **EC2 の inbound を一切開けず**、サーバ側は固定の
`pprotein-agent-<label>.<zone>` を見るだけでよい（環境差し替えは EC2 側の connector 設置のみ）。

> 補足: collector は Access の service token ヘッダを送れない。また
> `cloudflared access tcp` は `http://` origin では `bad handshake` になり使えない。
> そのため agent HTTP は **IP 許可（bypass）** で保護し、collector が直接取得する。
> 許可外 IP は 403、サーバからは 200 系（agent 応答）。
> 動作確認: `curl https://pprotein-agent-1.<zone>/` → ローカルから 403 /
> サーバから 404（agent の `/` 応答）。

## 認証の要点

- **UI**: Cloudflare Access の SSO（`allowed_emails`）。
- **pprotein SSH**: Access の service token（`non_identity`）+ SSH 鍵。
- **agent HTTP**: Access の **`bypass` + サーバ IP 許可**（collector がヘッダを送れず
  `access tcp` も使えないため）。
- **Tunnel connector**: トンネルごとの run token（サーバは cloud-init、agent は
  `measurement/cloudflared-agent.yml`。ホストごとに別トークン）。
- 詳細は [pprotein-server.md の「認証」](pprotein-server.md#認証) を参照。
