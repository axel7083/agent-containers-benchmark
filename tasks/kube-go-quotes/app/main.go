package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
)

var quotes = []string{"Simplicity is prerequisite for reliability.", "Make it work, make it right, make it fast."}

func main() {
	if os.Getenv("DB_PASSWORD") == "" {
		log.Fatal("DB_PASSWORD is required")
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	http.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) })
	http.HandleFunc("/ready", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ready")) })
	http.HandleFunc("/quotes", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(quotes)
	})
	log.Printf("quotes listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}
