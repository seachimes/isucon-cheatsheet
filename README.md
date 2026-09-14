# isucon-cheatsheet

ISUCON の準備・計測で使う手順と設定のチートシート。

## 計測ツール

nginx のアクセスログ解析（alp）、MySQL のスロークエリ解析（slp）、
計測ログのローテーションを Ansible で導入する。

- 手順書: [docs/measurement-tools.md](docs/measurement-tools.md)
- 実体: [ansible/measurement/](ansible/measurement/)

## SSH 公開鍵の配置

GitHub に登録した公開鍵（`https://github.com/<user>.keys`）を、対象ユーザー
（既定 `isucon`）の `authorized_keys` へ Ansible で登録する。

- 手順書: [docs/ssh-keys.md](docs/ssh-keys.md)
- 実体: [ansible/ssh-keys/](ansible/ssh-keys/)
pprotein のエージェント（pprotein-agent）、計測ログのローテーションを Ansible で導入する。

- 手順書: [docs/measurement-tools.md](docs/measurement-tools.md)
- 実体: [ansible/measurement/](ansible/measurement/)

## pprotein

- 競技用サーバのエージェント（pprotein-agent）: [docs/measurement-tools.md](docs/measurement-tools.md#pprotein-agent-の導入)
- pprotein サーバ本体（Akamai）: [docs/pprotein-server.md](docs/pprotein-server.md)
- 実体: [ansible/pprotein-server/](ansible/pprotein-server/)（Terraform は `pprotein-infra`）
