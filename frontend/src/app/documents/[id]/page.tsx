import { DocumentDetailPage } from "@/components/DocumentDetailPage";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function DocumentPage({ params }: Props) {
  const { id } = await params;
  return <DocumentDetailPage id={id} />;
}
