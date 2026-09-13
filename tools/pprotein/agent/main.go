// Log-only loopback entrypoint using the official pprotein handlers.
package main

import (
	"log"
	"net/http"
	"os"
	"strconv"

	"github.com/kaz/pprotein/integration"
)

func main() {
	port := os.Getenv("AGENT_PORT")
	if port == "" {
		port = "19000"
	}
	n, err := strconv.Atoi(port)
	if err != nil || n < 1024 || n > 65535 {
		log.Fatal("invalid AGENT_PORT")
	}
	debug := integration.NewDebugHandler()
	mux := http.NewServeMux()
	mux.Handle("/debug/log/httplog", debug)
	mux.Handle("/debug/log/slowlog", debug)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) })
	log.Fatal(http.ListenAndServe("127.0.0.1:"+port, mux))
}
