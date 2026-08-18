<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Alert, Button, ErrorMessage, FormControl, Select, Spinner, toast } from 'frappe-ui'

import { apiErrorMessage } from '@/api/client'
import { settingsApi } from '@/api/settings'

const loading = ref(true)
const saving = ref(false)
const disconnecting = ref(false)
const error = ref('')
const accessKey = ref('')
const secretKey = ref('')
const bucket = ref('')
const provider = ref('')
const region = ref('')
const endpoint = ref('')
const maxGb = ref(8)
const secretKeySet = ref(false)
const providers = ref([])

const connected = computed(() => Boolean(accessKey.value && bucket.value && secretKeySet.value))
const providerLabel = computed(
  () => providers.value.find((p) => p.value === provider.value)?.label || provider.value,
)
const isR2 = computed(() => provider.value === 'r2')
const endpointPlaceholder = computed(() =>
  isR2.value ? 'https://<account_id>.r2.cloudflarestorage.com' : 'https://s3.example.com (optional)',
)
const providerOptions = computed(() =>
  providers.value.map((p) => ({ label: p.label, value: p.value })),
)
const regionOptions = computed(
  () =>
    providers.value
      .find((p) => p.value === provider.value)
      ?.regions.map((r) => ({ label: r, value: r })) || [],
)

watch(provider, () => {
  if (!regionOptions.value.some((o) => o.value === region.value)) {
    region.value = regionOptions.value[0]?.value || ''
  }
})

// Every required field, so Connect stays dead until the form could succeed.
const canSave = computed(
  () =>
    Boolean(accessKey.value.trim()) &&
    Boolean(bucket.value.trim()) &&
    Boolean(provider.value) &&
    Boolean(region.value) &&
    (secretKeySet.value || Boolean(secretKey.value.trim())),
)

const load = async () => {
  loading.value = true
  try {
    const data = await settingsApi.get()
    providers.value = data.s3_providers || []
    const s3 = data.s3 || {}
    accessKey.value = s3.access_key || ''
    bucket.value = s3.bucket || ''
    provider.value = s3.provider || providers.value[0]?.value || ''
    region.value = s3.region || ''
    endpoint.value = s3.endpoint || ''
    maxGb.value = s3.max_gb ?? 8
    secretKeySet.value = !!s3.secret_key_set
  } catch (e) {
    error.value = e.message || 'Could not load settings.'
  } finally {
    loading.value = false
  }
}

const save = async () => {
  saving.value = true
  error.value = ''
  try {
    const result = await settingsApi.update({
      s3: {
        access_key: accessKey.value.trim(),
        secret_key: secretKey.value.trim(),
        bucket: bucket.value.trim(),
        provider: provider.value,
        region: region.value,
        endpoint: endpoint.value.trim(),
        max_gb: Number(maxGb.value),
      },
    })
    if (!result.error) {
      secretKey.value = ''
      toast.success('Object storage settings saved')
      await load()
    } else {
      error.value = apiErrorMessage(result, 'Could not save object storage settings.')
    }
  } catch (e) {
    error.value = e.message || 'Could not save object storage settings.'
  } finally {
    saving.value = false
  }
}

const disconnect = async () => {
  disconnecting.value = true
  try {
    const result = await settingsApi.update({ s3: { disconnect: true } })
    if (!result.error) {
      accessKey.value = ''
      secretKey.value = ''
      bucket.value = ''
      provider.value = providers.value[0]?.value || ''
      region.value = ''
      endpoint.value = ''
      maxGb.value = 8
      secretKeySet.value = false
      toast.success('Object storage disconnected')
    } else {
      toast.error(apiErrorMessage(result, 'Could not disconnect object storage.'))
    }
  } catch (e) {
    toast.error(e.message || 'Could not disconnect object storage.')
  } finally {
    disconnecting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="flex justify-center items-center h-40">
    <Spinner size="lg" class="text-ink-gray-4" />
  </div>

  <div v-else class="space-y-6">
    <Alert v-if="!connected" theme="blue" title="Why connect object storage?" :dismissible="false">
      <template #description>
        <p class="text-ink-gray-6 text-p-sm">
          Connect S3-compatible object storage to send offsite backups and snapshots.
        </p>
      </template>
    </Alert>

    <div
      v-if="connected"
      class="flex sm:flex-row flex-col sm:justify-between sm:items-center gap-3"
    >
      <div>
        <p class="font-medium text-ink-gray-8 text-base">Connected to {{ bucket }}</p>
        <p class="text-ink-gray-5 text-p-sm">{{ providerLabel }} · Access key {{ accessKey }}</p>
      </div>

      <Button
        class="flex-1 sm:flex-none"
        variant="subtle"
        theme="red"
        :loading="disconnecting"
        @click="disconnect"
        >Disconnect</Button
      >
    </div>

    <div class="space-y-4">
      <div class="flex sm:flex-row flex-col gap-4">
        <FormControl
          label="Bucket"
          type="text"
          v-model="bucket"
          placeholder="storage-bucket"
          class="w-full"
        />
        <FormControl
          label="Storage Limit (GB)"
          type="number"
          v-model="maxGb"
          min="0.5"
          max="100"
          step="0.5"
          help="Offsite uploads stop once the bucket reaches this size, keeping you inside the free tier."
          class="w-full sm:w-48"
        />
      </div>
      <div class="flex sm:flex-row flex-col gap-4">
        <Select label="Provider" v-model="provider" :options="providerOptions" class="w-full" />
        <Select label="Region" v-model="region" :options="regionOptions" class="w-full" />
      </div>

      <FormControl
        v-if="isR2 || endpoint"
        label="Endpoint"
        type="text"
        v-model="endpoint"
        :placeholder="endpointPlaceholder"
        help="Only needed for providers without a fixed endpoint, e.g. Cloudflare R2."
      />

      <div class="flex sm:flex-row flex-col gap-4">
        <FormControl
          label="Access Key"
          type="text"
          v-model="accessKey"
          placeholder="AKIA…"
          class="w-full"
        />
        <FormControl
          label="Secret Key"
          type="password"
          v-model="secretKey"
          :placeholder="secretKeySet ? '••••••••' : 'Secret key'"
          class="w-full"
        />
      </div>

      <ErrorMessage v-if="error" :message="error" />
      <div class="flex justify-end">
        <Button variant="solid" :loading="saving" :disabled="!canSave" @click="save">
          {{ connected ? 'Update' : 'Connect' }}
        </Button>
      </div>
    </div>
  </div>
</template>
