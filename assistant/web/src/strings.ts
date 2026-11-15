import { MAX_MESSAGE_LENGTH } from "@/config";

export const strings = {
  header: {
    title: "Assistente",
    newConversation: "Nuova conversazione",
  },
  simulation: {
    badge: "SIMULAZIONE",
    scenario: "Scenario simulato: Regate preliminari — sabato 26/09/2026",
  },
  home: {
    greeting: "Ciao!",
    question: "Dove vuoi andare?",
    subtitle: "Dimmi da dove parti e dove vai: ti trovo il percorso migliore.",
  },
  composer: {
    label: "Scrivi all'Assistente",
    placeholder: "Dove devi andare?",
    send: "Invia",
    tooLong: `Massimo ${MAX_MESSAGE_LENGTH} caratteri.`,
  },
  conversation: {
    log: "Conversazione",
    typing: "Sto scrivendo",
    quickChoices: "Scelte rapide",
  },
  sources: {
    title: "Fonti",
    asOf: (when: string) => `dati del ${when}`,
    badges: { real: "REALE", estimate: "STIMA", simulated: "SIMULATO" },
  },
  errors: {
    unavailable: "Non sono riuscito a rispondere. Riprova tra poco.",
    offline: "L'Assistente non è disponibile senza connessione.",
    rateLimit: "Troppe domande in poco tempo. Attendi qualche secondo.",
    auth: "Per usare l'Assistente accedi a Sentrix.",
    retry: "Riprova",
    login: "Accedi a Sentrix",
  },
} as const;
