# Startup Outline

## Goal

Keep most heavy load on `raspberry`, while `pi` mainly handles coordination, UI, and reporting.

## Recommended Node Split

### `raspberry`

- `codegen_nlp-trainer-cpu`
- `dataset_dataset-puller-node2`
- Any future heavy cache-building or large dataset indexing

### `pi`

- `skynetv2_web-v2`
- `skynetv2_portainer`
- `dataset_dataset-puller-node1`
- `skynetv2_nlp-trainer-cpu-skynetv1`
- `codegen_email-reporter`

## Parked Until Later

- `skynetv2_nlp-trainer-cpu-skynetv5-v2`

Start it only after `skynetv1` is finished and the target dataset path exists.

## Startup Checks

Before next week's test:

1. Confirm both swarm nodes are `Ready`.
2. Confirm these mounts exist on the node that will run the service:
   - `/mnt/dataset_storage`
   - `/mnt/shared`
   - `/mnt/toshiba`
   - `/mnt/webcode`
   - `/mnt/1tb`
   - `/mnt/nfs_shared`
3. Confirm `.env` still has working SMTP credentials.
4. Confirm `docker service ls` shows:
   - `codegen_nlp-trainer-cpu` on `raspberry`
   - `dataset_dataset-puller-node1` on `pi`
   - `dataset_dataset-puller-node2` on `raspberry`
   - `codegen_email-reporter` on `pi`
5. Keep `skynetv2_nlp-trainer-cpu-skynetv5-v2=0` until needed.

## Notes

- The reporter is intentionally on `pi` because it is lightweight and benefits from local repo access.
- The broad dataset scan trainer is intentionally on `raspberry` because that is the high-load path.
