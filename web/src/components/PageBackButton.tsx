import { ArrowLeftIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useNavigate } from "@/lib/routing";
import { cn } from "@/lib/utils";

interface PageBackButtonProps {
  fallbackTo: string;
  children: ReactNode;
  className?: string;
}

export function PageBackButton({ fallbackTo, children, className }: PageBackButtonProps) {
  const navigate = useNavigate();

  const goBack = () => {
    const historyIndex = window.history.state?.idx;
    if (typeof historyIndex === "number" && historyIndex > 0) {
      navigate(-1);
      return;
    }
    navigate(fallbackTo);
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={cn("-ml-2", className)}
      onClick={goBack}
    >
      <ArrowLeftIcon className="size-4" />
      {children}
    </Button>
  );
}
