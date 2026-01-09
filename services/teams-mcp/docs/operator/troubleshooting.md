# Troubleshooting Guide

## Deployment Issues

### Pod Not Starting

**Symptom**: Pod stuck in `CrashLoopBackOff` or `Error` state

**Check logs**:
```bash
kubectl logs -n teams-mcp deploy/teams-mcp --previous
```

**Common causes**:

| Error | Cause | Solution |
|-------|-------|----------|
| `ECONNREFUSED` to PostgreSQL | Database unreachable | Verify `DATABASE_URL` and network policies |
| `ECONNREFUSED` to RabbitMQ | Message queue unreachable | Verify `AMQP_URL` and network policies |
| `Invalid ENCRYPTION_KEY` | Key wrong format/length | Must be 64-character hex string |
| `Invalid AUTH_HMAC_SECRET` | Key wrong format/length | Must be 64-character hex string |

### Migration Failed

**Symptom**: Migration job fails, pod doesn't start

**Check migration logs**:
```bash
kubectl logs -n teams-mcp job/teams-mcp-migration
```

**Common causes**:
- Database connection issues
- Insufficient database permissions
- Previous migration state inconsistent

**Manual recovery**:
```bash
# Connect to database
kubectl exec -it deploy/teams-mcp -- psql $DATABASE_URL

# Check migration status
SELECT * FROM _prisma_migrations ORDER BY finished_at DESC;
```

### External Access Not Working

**Symptom**: External requests return 502/503

**Verify**:
```bash
# Check service endpoints
kubectl get endpoints -n teams-mcp

# Check Kong route (if using Kong)
kubectl get httproute -A | grep teams-mcp

# Test internal connectivity
kubectl run -it --rm debug --image=curlimages/curl -- curl http://teams-mcp:51345/health
```

## Authentication Issues

### Login "Flicker" on Reconnection

**Symptom**: User sees a quick flicker or brief redirect sequence when reconnecting after the first connection

**This is normal behavior** - not a bug or issue. After a user has connected once and granted permission, Microsoft Entra ID uses silent authentication. The browser quickly redirects through the OAuth flow to validate the existing session, creating a brief "flicker" effect. This is standard Microsoft OAuth behavior.

**See**: [User Reconnection Experience](../operator/authentication.md#user-reconnection-experience-the-login-flicker) for detailed explanation.

### OAuth Flow Fails

**Symptom**: Users cannot complete Microsoft sign-in

**Check**:
1. Redirect URI matches exactly (including trailing slash)
2. Client ID and secret are correct
3. Admin consent granted for required permissions

**Debug**:
```bash
# Check logs for OAuth errors
kubectl logs -n teams-mcp deploy/teams-mcp | grep -i "oauth\|auth\|AADSTS"
```

### Token Refresh Fails

**Symptom**: Graph API calls fail with 401 after working initially

**Causes**:
- Microsoft refresh token expired (~90 days of inactivity)
- User revoked app consent
- Client secret rotated

**Solution**: User must reconnect to the MCP server

### Webhook Validation Fails

**Symptom**: Microsoft Graph subscriptions fail to create

**Check**:
1. `MICROSOFT_WEBHOOK_SECRET` is set correctly
2. Webhook endpoint is publicly accessible via HTTPS
3. Kong/gateway is routing traffic correctly to the service

**Test webhook endpoint**:
```bash
curl -X POST https://teams.mcp.example.com/transcript/notification \
  -H "Content-Type: application/json" \
  -d '{"validationToken": "test"}'
```

## Processing Issues

### Transcripts Not Appearing

**Symptom**: Meeting transcripts not uploaded to Unique

**Check**:

1. **User has active subscription**:
```bash
kubectl logs -n teams-mcp deploy/teams-mcp | grep -i "subscription"
```

2. **Webhook notifications received**:
```bash
kubectl logs -n teams-mcp deploy/teams-mcp | grep -i "notification"
```

3. **RabbitMQ queue**:
```bash
# Check queue depth
kubectl exec -it deploy/rabbitmq -- rabbitmqctl list_queues
```

4. **Processing errors**:
```bash
kubectl logs -n teams-mcp deploy/teams-mcp | grep -i "error\|failed"
```

### Messages Stuck in Dead Letter Queue

**Symptom**: Messages accumulating in DLX queue

**Check DLQ**:
```bash
kubectl exec -it deploy/rabbitmq -- rabbitmqctl list_queues name messages | grep dlx
```

**Common causes**:
- Unique API unavailable
- Graph API rate limiting
- Invalid transcript format

**Reprocess messages**:
```bash
# Move messages from DLQ back to main queue (use RabbitMQ management UI)
```

### Graph API Rate Limiting

**Symptom**: Intermittent failures with 429 responses

**Check logs**:
```bash
kubectl logs -n teams-mcp deploy/teams-mcp | grep -i "429\|rate\|throttl"
```

**Solutions**:
- Reduce `UNIQUE_USER_FETCH_CONCURRENCY`
- Implement backoff (automatic in service)
- Contact Microsoft for higher limits

## Database Issues

### Connection Pool Exhausted

**Symptom**: `too many connections` errors

**Check**:
```bash
# Count active connections
kubectl exec -it deploy/teams-mcp -- psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"
```

**Solutions**:
- Increase PostgreSQL `max_connections`
- Review connection pool settings
- Check for connection leaks

### Database Full

**Symptom**: Write operations fail

**Check**:
```bash
kubectl exec -it deploy/teams-mcp -- psql $DATABASE_URL -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

**Solutions**:
- Run token cleanup job manually
- Increase database storage
- Archive old data

## RabbitMQ Issues

### Queue Buildup

**Symptom**: Messages accumulating faster than processing

**Check**:
```bash
kubectl exec -it deploy/rabbitmq -- rabbitmqctl list_queues name messages consumers
```

**Solutions**:
- Check pod logs for processing errors
- Verify Unique API is responsive
- Increase pod resources if CPU/memory constrained

### Connection Lost

**Symptom**: `ECONNRESET` or connection timeout errors

**Check**:
- RabbitMQ pod health
- Network policies allowing traffic
- RabbitMQ resource limits

## Monitoring and Alerts

### Prometheus Metrics Not Appearing

**Check**:
```bash
# Verify metrics endpoint
kubectl port-forward -n teams-mcp svc/teams-mcp 51346:51346
curl http://localhost:51346/metrics
```

**Verify ServiceMonitor**:
```bash
kubectl get servicemonitor -n teams-mcp
```

### Grafana Dashboard Empty

**Check**:
- Dashboard ConfigMap exists
- Grafana can read from namespace
- Prometheus is scraping metrics

## Log Analysis

### Enable Debug Logging

```yaml
server:
  env:
    LOG_LEVEL: debug
```

### Common Log Patterns

| Pattern | Meaning |
|---------|---------|
| `subscription created` | Graph webhook subscription successful |
| `notification received` | Incoming webhook from Microsoft |
| `transcript processed` | Successfully uploaded to Unique |
| `token refreshed` | Microsoft token refresh successful |
| `AADSTS*` | Microsoft authentication error |

### Log Aggregation Query Examples

**Find authentication errors**:
```
{app="teams-mcp"} |~ "AADSTS|auth.*error|401"
```

**Find processing failures**:
```
{app="teams-mcp"} |~ "failed|error" |~ "transcript|recording"
```

## Getting Help

1. **Check existing documentation**:
   - [Architecture](../technical/architecture.md)
   - [Token Flows](../technical/token-auth-flows.md)
   - [Permissions](../technical/permissions.md)

2. **Collect diagnostic information**:
   - Pod logs
   - Events: `kubectl get events -n teams-mcp`
   - Resource status: `kubectl describe pod -n teams-mcp`

3. **Contact support** with:
   - Kubernetes version
   - Helm chart version
   - Relevant log excerpts
   - Steps to reproduce
