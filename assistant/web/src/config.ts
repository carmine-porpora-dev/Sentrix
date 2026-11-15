export const MAX_MESSAGE_LENGTH = 500;

/** Il tempo massimo di attesa di una risposta: 25 s di strumenti lato servizio (10 §5.1) più il margine di rete. */
export const REQUEST_TIMEOUT_MS = 35_000;

export const COMPOSER_MIN_HEIGHT = 40;
/** Quattro righe, poi il campo scorre dentro. */
export const COMPOSER_MAX_HEIGHT = 112;

/** Sotto questa larghezza: layout telefono, Invio va a capo e si invia solo col pulsante. */
export const COMPACT_QUERY = "(max-width: 599.98px)";
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Moltiplicatore degli alfa dello sfondo liquido (0,5 più discreto, 1 più presente). */
export const LIQUID_INTENSITY = 0.8;
/** L'istante del fotogramma fermo con `prefers-reduced-motion`. */
export const LIQUID_STILL_TIME = 3;
export const LIQUID_SPEED = 0.55;
export const LIQUID_MAX_DPR = 2;

export const CHAT_PATH = "api/chat";
export const LOGIN_URL = "/";
