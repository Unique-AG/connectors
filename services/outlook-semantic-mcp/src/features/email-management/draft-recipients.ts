export function toGraphRecipients(recipients: Array<{ name?: string; email: string }>) {
  return recipients.map((item) => ({
    emailAddress: {
      address: item.email,
      ...(item.name && { name: item.name }),
    },
  }));
}
