interface NamedCompany {
  companyName?: string;
  englishName?: string;
}

interface TitledOrder {
  orderId?: string | number;
  productDetails?: { productName?: string };
  companyDetails?: { companyName?: string };
}

export function companyTitle(company: NamedCompany | undefined): string | undefined {
  return company?.companyName || company?.englishName || undefined;
}

export function orderTitle(order: TitledOrder | undefined): string | undefined {
  const parts = [order?.productDetails?.productName, order?.companyDetails?.companyName].filter(
    (part): part is string => Boolean(part),
  );
  if (parts.length > 0) {
    return parts.join(' - ');
  }
  return order?.orderId === undefined ? undefined : `Kyckr order ${order.orderId}`;
}
