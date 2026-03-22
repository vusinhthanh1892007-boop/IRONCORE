import { BarChart2, MessageCircle, Puzzle, Settings } from "lucide-react";
import { Brain } from "lucide-react";

export const navItems = [
  {
    label: "Chat",
    href: "/chat",
    icon: MessageCircle,
  },
  {
    label: "Dashboard",
    href: "/dashboard",
    icon: BarChart2,
  },
  {
    label: "Plugins",
    href: "/plugins",
    icon: Puzzle,
  },
  {
    label: "AI Catalog",
    href: "/ai-catalog",
    icon: Brain,
  },
  {
    label: "Settings",
    href: "/settings",
    icon: Settings,
  },
];
