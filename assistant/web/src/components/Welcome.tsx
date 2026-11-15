import { LiquidBackground } from "@/components/LiquidBackground";
import { Logo } from "@/components/Logo";
import { strings } from "@/strings";

/** La vista iniziale: lo sfondo liquido, il logo e il benvenuto, centrati. */
export function Welcome() {
  return (
    <>
      <div aria-hidden="true" className="absolute inset-0 z-0">
        <LiquidBackground />
      </div>
      <div className="relative z-[1] flex min-h-0 flex-1 items-center justify-center px-6 pb-2 pt-16 text-center sm:px-8 sm:pt-8">
        <div className="flex animate-enter flex-col items-center">
          <div className="mb-5">
            <Logo width={48} height={72} />
          </div>
          <h1 className="m-0 mb-3 text-2xl [text-wrap:balance]">
            <span className="block">{strings.home.greeting}</span>
            <span className="block">{strings.home.question}</span>
          </h1>
          <p className="m-0 max-w-[280px] text-md opacity-[0.82] [text-wrap:pretty]">
            {strings.home.subtitle}
          </p>
        </div>
      </div>
    </>
  );
}
