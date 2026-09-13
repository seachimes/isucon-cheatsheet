# pproteinを本番前に準備する

このディレクトリを持ち込み、inventoryの接続先とログパスを埋めて使う。
Ubuntu/systemd、Python 3、SSHとsudoが使えるサーバー向け。既存nginx/MySQLの設定やDBは変更しない。

## 何を作るか

| 場所 | 内容 |
|---|---|
| 各サーバー | ログ専用agent。127.0.0.1:19000、nginx/MySQLログを取得 |
| Goアプリ内 | 任意で追加する127.0.0.1:19001の計測入口 |
| Mac | pprotein UI（127.0.0.1:9000）、alp/slp、計測データ保存 |
| SSH | Macの19101〜19103をログ、19201〜19203をGo計測へ転送 |

公式pprotein **v1.2.4** を固定。agentは公式ライブラリのログハンドラーを利用する小さな起動プログラム。
公式agentは全インターフェースで待ち受けるため、ここではlocalhost限定・ログ専用の入口にしている。
agent自身のpprofは公開しない。アプリCPU計測は必ずGoアプリの19001へ向ける。

## 1. 手元の準備（本番前に済ませる）

```sh
cd tools/pprotein
# macOS。導入済みなら不要。
brew install go node graphviz python
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
bash scripts/build-agent.sh
bash scripts/setup-ui.sh
```

Goは1.23.3以上、Ansibleの手元Pythonは3.11以上。slpのビルドにはCコンパイラ（macOSのCommand Line Tools）も必要。
依存ツールのGo要件によっては新しいtoolchainもダウンロードされる。
setup-uiはタグのcommitを検証してからUIの待受だけlocalhostに変更しビルドする。
alp v1.0.21 / slp v0.2.1も手元の `.artifacts/bin` に入れる。Git・npm・Go配布元へのネットワーク接続が必要。
Linux amd64/arm64用agentを `.artifacts/` に作るので、本番前にビルドしておく。

## 2. 接続先・役割を設定

`examples/isucon14.yml` をコピーして編集する。ホスト名にはSSH configのエイリアスを使える。
任意の環境では `ansible_host`、`ansible_user`、`ansible_port` を設定可能。特殊な鍵や踏み台はSSH configへ記載する。
`ansible_ssh_common_args`等はlocal.pyには転用しないので、Ansible専用オプションに依存しないこと。

- nginxがある台：`pprotein_collect_http: true`
- MySQLがある台：`pprotein_collect_sql: true`
- 計測機能を組み込んだGoがある台：`pprotein_collect_go: true`
- 無い役割はfalse。agentを全台に置いても、収集対象はこの値で選ぶ。
- 各台のMac側ポートは重複させない。

**例のMySQLログパスは2026-09-13の確認値。実際の `SHOW VARIABLES LIKE 'slow_query_log_file'` で必ず確認する。**
nginxはalpが読めるLTSVにし、`reqtime:$request_time`等の処理時間を含める。
SQLログは有効化と閾値を別途設定する。50msの閾値なら短いSQLは収集できない。
ログ設定変更は別の変更としてバックアップし、nginxは配置前に検証する。今回のPlaybookは設定を上書きしない。

## 3. まず1台へAnsibleで導入

以下はapp3の例。実行ログはGit対象外の `.runs/` に保存する。
毎回新しいchange IDを使い、同時に別の導入・復元を実行しない。

```sh
change_id="$(date -u +%Y%m%dT%H%M%SZ)-app3"
mkdir -p .runs
ansible-playbook -i examples/isucon14.yml playbooks/deploy.yml \
  --limit isucon14-app3 -e "change_id=$change_id" --check --diff

set -o pipefail
ansible-playbook -i examples/isucon14.yml playbooks/deploy.yml \
  --limit isucon14-app3 -e "change_id=$change_id" \
  2>&1 | tee ".runs/$change_id.log"
```

複数台を一度に指定すると拒否する。成功したらapp1/app2も別IDで適用する。
`--check`ではバックアップ・サービス操作・HTTP確認は行わない。初回の実適用を完全に保証するものではない。
収集有効なログファイルが存在しなければ、配置前に停止する。

配置は `/opt/isucon-pprotein/{agent,agent.env}` と `isucon-pprotein-agent.service`。
ログのchmodや所有者変更を避けるためagentはrootで起動するが、systemdでファイルシステムを読み取り専用にし、capabilityはログを読むためのCAP_DAC_READ_SEARCHに限定する。
rootプロセスであることは変わらない。非root必須の環境ではログ権限・ローテーションを設計してから利用する。
通常のGoアプリをrootに変えることはしない。localhostのログAPIは同じサーバーの他ユーザーからも接続できる。

## 4. Macから接続する

```sh
# ターミナルA：接続を維持。Ctrl-Cで切断。
python3 scripts/local.py tunnel -i examples/isucon14.yml --hosts isucon14-app3

# ターミナルB：分析画面を起動。
bash scripts/start-ui.sh

# ターミナルC：pproteinのgroup/targets用JSONを生成。
python3 scripts/local.py targets -i examples/isucon14.yml \
  --hosts isucon14-app3 --seconds 60 > .artifacts/targets.json
```

ブラウザで `http://127.0.0.1:9000` を開き、Settingsのgroup/targetsに生成したJSONを保存する。
APIで反映する場合（手元のpprotein設定だけが変わる）：

```sh
curl --fail -H 'Content-Type: application/json' \
  --data-binary @.artifacts/targets.json http://127.0.0.1:9000/api/group/targets
```

alpのURLまとめ設定も競技アプリに合わせる。既定値はmock用なのでそのままではID付きURLが分散する。
3台を収集するときは `--hosts isucon14-app1,isucon14-app2,isucon14-app3`。
Goの追加は [組み込み手順](examples/go-integration.md) を使う。役割を移したらinventoryを更新し、トンネルを再起動してtargetsも更新する。

## 5. 計測する

pproteinの収集を開始し、その期間にベンチの負荷走行を重ねる。
ログ収集は開始後に追記された範囲を読むので、終了後の収集ではそのベンチのログを取得できない。
初期化・DBバックアップ・復元が混ざらないように負荷区間で計測する。
**このチートシートはベンチを起動しない。DBの保存・復旧は運用リポジトリ側の手順で行う。**
計測結果は `data/` に保存される。秘密情報を含み得るためGitへ追加しない。

## 元へ戻す

適用前の3ファイル・権限・サービス起動状態を `/var/backups/isucon-pprotein/<change_id>/` に保存する。
配置や検証に失敗した場合は自動復元を試みる。SSH切断や復旧失敗時は同じIDで以下を実行する。

```sh
ansible-playbook -i examples/isucon14.yml playbooks/rollback.yml \
  --limit isucon14-app3 -e "change_id=$change_id"
```

最新の導入に対応するIDを使う。その後の変更を誤って上書きしないよう、古いスナップショットへの復元は拒否する。
初回導入前に戻す場合はagentを停止・無効化し、追加した3ファイルを削除する。
空ディレクトリ、復旧ツール、バックアップは保全のため残す。
既存agentへ戻す場合は元ファイル・mode・uid/gid・enabled/active状態を復元する。
チェックサム不一致ならサービスを止める前に拒否する。復旧済みIDの再実行は何もしない。
復旧後は従来の収集結果とサービス状態を確認する。Goアプリの組み込みやDBはこの復元対象に含まれない。

## ローカル検証

```sh
python3 -m unittest discover -s tests -v
ansible-playbook -i examples/isucon14.yml playbooks/deploy.yml \
  --syntax-check --limit isucon14-app3 -e change_id=test
ansible-playbook -i examples/isucon14.yml playbooks/rollback.yml \
  --syntax-check --limit isucon14-app3 -e change_id=test
```

実サーバーでの適用・systemd隔離・復元は別途1台で検証する。
固定したv1.2.4のフロントエンド依存にはnpm auditで19件（moderate 6 / high 13）の指摘が出た。互換性を変える自動更新は行っていない。UIはlocalhost限定で使用する。
参考：[pprotein v1.2.4](https://github.com/kaz/pprotein/tree/v1.2.4)、[公式計測実装](https://github.com/kaz/pprotein/blob/v1.2.4/integration/integration.go)。
