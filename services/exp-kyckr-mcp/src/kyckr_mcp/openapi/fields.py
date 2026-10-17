# Download links stay out of the schema. The tools remove them from the answer.
RESPONSE_FIELDS = {
    "OrderDetails": (
        "orderId",
        "orderDate",
        "customerReference",
        "status",
        "cost",
        "user",
        "productDetails",
        "companyDetails",
    )
}
