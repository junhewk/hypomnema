import { DocumentDetailPage } from "@/components/DocumentDetailPage";

interface Props {
  params: Promise<{ id: string }>;
}

export function generateStaticParams(): Array<{ id: string }> {
  return [{ id: "__export_placeholder__" }];
}

export default async function DocumentPage({ params }: Props) {
  const { id } = await params;
  return <DocumentDetailPage id={id} />;
}
