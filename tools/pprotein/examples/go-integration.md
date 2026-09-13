# GoアプリのCPU計測を有効にする

agentはログ収集専用。Go内部の計測はアプリに組み込む。
アプリ側のGoバージョンと依存差分を確認してから次を追加する。

```sh
go get github.com/kaz/pprotein@v1.2.4
```

アプリのmain関数に追加（chiでも利用可能）：

```go
import "github.com/kaz/pprotein/integration/standalone"

// 通常のHTTPサーバー起動前。必ずgoroutineで起動する。
go standalone.Integrate("127.0.0.1:19001")
```

19000はログagent、19001はGoアプリ。Goプロファイルをagentに向けない。
このGo用入口にも公式のログ取得機能はあるが、収集先には19000を使う。
組み込み前のgo.mod/go.sum、ソース、実行バイナリを保存する。
ビルド・アプリ再起動・API確認をアプリ固有のデプロイ手順で行う。
問題時は以前のバイナリと設定へ戻して再起動する。DB初期化は不要。
Ansibleのagent復元はGoアプリのデプロイを戻すものではない。

成功後、inventoryの対象ホストで `pprotein_collect_go: true` にする。
アプリを別ホストへ移したらこの値を移動し、接続スクリプトとtargetsを再生成する。
