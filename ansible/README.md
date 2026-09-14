# 計測基盤の inventory / 環境プロファイル

計測基盤は **pprotein サーバ1台を全環境で使い回し**、競技環境（EC2 など）だけを
差し替えて使う。環境は2つの部品で表現する。

| 部品 | 場所 | 内容 |
| --- | --- | --- |
| 共有サーバ | `inventories/pprotein_server/hosts` | pprotein サーバ（Tunnel SSH）。全環境共通 |
| 競技環境 | `inventories/<env>/hosts` | 競技用サーバ（`[app]` / `[bench]`） |
| 環境プロファイル | `envs/<env>.yml` | nginx サイト名・公開ディレクトリ・ログパスなど |

`hosts` は環境固有（IP 等）なので gitignore 済み。`inventories/examples/` の例を
コピーして使う（`examples/` は `-i` の対象外なので Ansible には読まれない）。

```
cp inventories/examples/pprotein_server.hosts inventories/pprotein_server/hosts
cp inventories/examples/private-isu.hosts        inventories/private-isu/hosts
```

## 使い方

### pprotein サーバ（共有・初回のみ / 更新時）

```sh
ansible-playbook -i inventories/pprotein_server pprotein-server/bootstrap.yml \
  -e pprotein_server_hosts=pprotein_server
ansible-playbook -i inventories/pprotein_server pprotein-server/deploy.yml \
  -e pprotein_server_hosts=pprotein_server
```

### 競技環境の計測ツール（環境ごとに差し替え）

```sh
# private-isu
ansible-playbook -i inventories/private-isu measurement/pprotein-agent.yml \
  -e measure_hosts=app -e @envs/private-isu.yml

# isucon14
ansible-playbook -i inventories/isucon14 measurement/pprotein-agent.yml \
  -e measure_hosts=app -e @envs/isucon14.yml
```

環境を切り替えるときは `-i` と `-e @` を変えるだけ。サーバ側は触らない。
