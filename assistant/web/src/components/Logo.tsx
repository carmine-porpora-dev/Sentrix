import logo from "@/assets/sentrix-icon.svg";

/** Il logo compatto di Sentrix; la misura la decide chi lo usa (48×72 nella home, 16×24 nell'intestazione). */
export function Logo({ width, height }: { width: number; height: number }) {
  return (
    <img
      src={logo}
      alt=""
      width={width}
      height={height}
      className="block"
      style={{ width, height }}
    />
  );
}
