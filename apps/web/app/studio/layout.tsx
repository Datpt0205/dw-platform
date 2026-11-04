"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Layout, Menu } from "antd";
import { t } from "./_meta/messages";
import { STUDIO_SECTIONS } from "./_meta/sections";

/** The section whose href is the longest prefix of the path, else "all". */
function selectedKey(pathname: string): string {
  let best = "/studio";
  for (const section of STUDIO_SECTIONS) {
    const inside =
      pathname === section.href || pathname.startsWith(`${section.href}/`);
    if (inside && section.href.length > best.length) best = section.href;
  }
  return best;
}

/**
 * Studio's own frame inside the shell: a menu of its areas, the first being
 * every artifact, then one per `STUDIO_SECTIONS` entry. Horizontal, so it
 * folds into antd's overflow menu at a phone's width instead of taking a
 * column of it.
 */
export default function StudioLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const items = [
    { key: "/studio", label: <Link href="/studio">{t("menu.all")}</Link> },
    ...STUDIO_SECTIONS.map((section) => ({
      key: section.href,
      label: <Link href={section.href}>{section.label}</Link>,
    })),
  ];
  return (
    <Layout className="mx-auto max-w-6xl">
      <nav aria-label={t("menu.label")} className="mb-4 min-w-0">
        <Menu
          mode="horizontal"
          selectedKeys={[selectedKey(pathname)]}
          items={items}
        />
      </nav>
      <Layout.Content className="min-w-0">{children}</Layout.Content>
    </Layout>
  );
}
