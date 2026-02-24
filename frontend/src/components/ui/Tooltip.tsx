import React from "react";
import * as T from "@radix-ui/react-tooltip";
import { HelpCircle } from "lucide-react";

interface InfoTooltipProps {
  content: string;
}

export const InfoTooltip: React.FC<InfoTooltipProps> = ({ content }) => (
  <T.Root delayDuration={300}>
    <T.Trigger asChild>
      <span className="inline-flex items-center ml-1 text-gray-500 hover:text-gray-300 cursor-help align-middle">
        <HelpCircle size={12} />
      </span>
    </T.Trigger>
    <T.Portal>
      <T.Content
        side="top"
        sideOffset={5}
        className="z-50 max-w-xs rounded bg-gray-800 border border-gray-600 px-2.5 py-1.5 text-xs text-gray-200 shadow-lg leading-snug"
      >
        {content}
        <T.Arrow className="fill-gray-800" />
      </T.Content>
    </T.Portal>
  </T.Root>
);
