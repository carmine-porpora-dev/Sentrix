export type Dict = Record<string, string>;

export interface DesignTokens {
  name: string;
  source: string;
  extracted: string;
  theme: string;
  tokens: Record<string, Record<string, string>>;
}

export type FontSizeEntry = [
  size: string,
  options: { lineHeight: string; fontWeight: string; letterSpacing: string },
];

export interface TokenTheme {
  colors: Dict;
  fontFamily: Dict;
  fontSize: Record<string, FontSizeEntry>;
  spacing: Dict;
  strokeWidth: Dict;
  borderRadius: Dict;
  borderWidth: Dict;
  opacity: Dict;
  transitionDuration: Dict;
  transitionTimingFunction: Dict;
  screens: Dict;
}

export interface TailwindTokens {
  extend: TokenTheme;
  utilities: Record<string, Record<string, string>>;
}
