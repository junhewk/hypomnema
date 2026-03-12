import { EngramDetailPage } from "@/components/EngramDetailPage";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EngramPage({ params }: Props) {
  const { id } = await params;
  return <EngramDetailPage id={id} />;
}
