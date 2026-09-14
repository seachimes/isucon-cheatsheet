# isucon-cheatsheet

ISUCON の準備・計測で使う手順と設定のチートシート。

## 計測ツール

nginx のアクセスログ解析（alp）、MySQL のスロークエリ解析（slp）、
pprotein のエージェント（pprotein-agent）、計測ログのローテーションを Ansible で導入する。

- 手順書: [docs/measurement-tools.md](docs/measurement-tools.md)
- 実体: [ansible/measurement/](ansible/measurement/)

## pprotein

- 全体像（リリース戦略・サーバ/エージェント/EC2/VPC の関係）: [docs/architecture.md](docs/architecture.md)
- 競技用サーバのエージェント（pprotein-agent）: [docs/measurement-tools.md](docs/measurement-tools.md#pprotein-agent-の導入)
- pprotein サーバ本体（Akamai）: [docs/pprotein-server.md](docs/pprotein-server.md)
- 実体: [ansible/pprotein-server/](ansible/pprotein-server/)（Terraform は `pprotein-infra`）
