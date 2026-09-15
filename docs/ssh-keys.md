# SSH 公開鍵の配置（GitHub の公開鍵を isucon ユーザーへ）

ISUCON 環境では、選手が GitHub に登録した SSH 公開鍵を使って `isucon` ユーザーで
SSH 接続する運用が多い。private-isu の Ansible で行っていた鍵配置を、任意の過去問
環境で使えるようプレースホルダ化して移植したもの。

Ansible の独立 playbook として実行する。`playbooks.yml` からは import しない。

## 仕組み

Ansible の [`ansible.posix.authorized_key`](https://docs.ansible.com/ansible/latest/collections/ansible/posix/authorized_key_module.html)
モジュールは `key` に **URL** を渡すと、その内容を取得して `authorized_keys` へ登録する。
GitHub の `https://github.com/<user>.keys` はコメント無しの公開鍵一覧を返すため、
これを `loop` でユーザー分だけ流す。

- 冪等（何度実行しても重複登録しない）
- `exclusive` は既定の `no` なので既存鍵は消さない
- private-isu の `authorized_key: user=isucon key="https://github.com/{{ item }}.keys"` と同じ

## ディレクトリ構成

```
ansible/
├── hosts.example              # inventory のサンプル
└── ssh-keys/
    ├── vars.yml               # 共通変数（登録ユーザー・対象ユーザー）
    └── github.yml             # 公開鍵の登録
```

## 事前準備

1. inventory を作成する。

   ```sh
   cd ansible
   cp hosts.example hosts
   ```

   対象ホスト（グループ）を `hosts` に書く。以降の例では `isu-app` を対象にする。

2. `ansible.posix` コレクションを用意する。`ansible` パッケージなら同梱。
   ansible-core のみの場合は次を実行する。

   ```sh
   ansible-galaxy collection install ansible.posix
   ```

3. SSH 疎通を確認する。

   ```sh
   ansible -i hosts isu-app -m ping
   ```

## 実行

```sh
cd ansible
ansible-playbook -i hosts ssh-keys/github.yml -e github_key_hosts=isu-app
```

この playbook は以下を行う。

1. 対象ユーザー（既定 `isucon`）が無ければ作成（`github_key_create_user`）
2. 対象ユーザーへ NOPASSWD sudo を付与（`github_key_grant_sudo`）
3. `github_key_users` の各 GitHub ユーザーの公開鍵を `authorized_keys` へ登録

ユーザーを変える場合は extra-vars で上書きする。

```sh
# 登録する GitHub ユーザーを変える
ansible-playbook -i hosts ssh-keys/github.yml \
  -e github_key_hosts=isu-app \
  -e '{"github_key_users":["wtnqk","seachimes"]}'

# 対象ユーザーを ubuntu にする
ansible-playbook -i hosts ssh-keys/github.yml \
  -e github_key_hosts=isu-app \
  -e github_key_target_user=ubuntu
```

確認:

```sh
ssh isucon@isu-app 'cat ~/.ssh/authorized_keys'
```

## 変数一覧

`ssh-keys/vars.yml` の既定値。`-e key=value` で上書きできる。

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `github_key_hosts` | （必須） | 対象ホスト/グループ。`measure_hosts` と同様に必須 |
| `github_key_users` | `[wtnqk, seachimes, meron14725]` | 鍵を登録する GitHub ユーザー名のリスト |
| `github_key_target_user` | `isucon` | 鍵を登録する対象ユーザー |
| `github_key_create_user` | `true` | 対象ユーザーが無ければ作成する |
| `github_key_grant_sudo` | `true` | 対象ユーザーへ NOPASSWD sudo を付与する |

## 注意

- `github_key_hosts` は必須。指定しないと `hosts` が解決できずエラーになる。
- 鍵取得のため、対象ホスト（または Ansible 実行ホスト）から `github.com` へ
  到達できる必要がある。
- 対象ユーザーの作成・sudo 付与が不要な環境（既に整備済み）では
  `-e github_key_create_user=false -e github_key_grant_sudo=false` を付ける。
- `ubuntu` ユーザーにも入れたい場合は、対象ユーザーを変えて 2 回実行するか、
  `github_key_target_user` を `ubuntu` にして実行する。
