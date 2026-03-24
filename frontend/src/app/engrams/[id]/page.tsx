import { EngramDetailPage } from "@/components/EngramDetailPage";

interface Props {
  params: Promise<{ id: string }>;
}

export function generateStaticParams(): Array<{ id: string }> {
  return [{ id: "__export_placeholder__" }];
}

export default async function EngramPage({ params }: Props) {
  const { id } = await params;
  return <EngramDetailPage id={id} />;
}
