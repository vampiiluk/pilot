<script setup lang="ts">
import { useRouter } from 'vue-router'
import { computed, onMounted, ref } from 'vue'
import {
  Badge,
  Button,
  Dialog,
  Dropdown,
  type DropdownItem,
  ErrorMessage,
  LoadingText,
  Select,
  toast,
} from 'frappe-ui'

import EmptyState from '@/components/common/EmptyState.vue'
import ListSkeleton from '@/components/common/ListSkeleton.vue'
import Table from '@/components/common/Table.vue'
import BackupConfigDialog from '@/components/sites/BackupConfigDialog.vue'
import RestoreDialog from '@/components/sites/RestoreDialog.vue'

import { sitesApi } from '@/api/sites'
import { tasksApi } from '@/api/tasks'
import { cronToLabel } from '@/utils/backup'
import { apiErrorMessage, hasApiError } from '@/api/client'
import type { Backup, BackupFile, BackupSchedule } from '@/types/siteBackups'
import { fmtDateTime } from '@/utils/taskFormat'
import { useSite } from '@/composables/sites/useSite'
import { openTaskDetailPage } from '@/utils/taskRoute'

interface Props {
  siteName: string
}

const props = defineProps<Props>()
const router = useRouter()

const {
  backups,
  backupsLoading,
  backupsHasMore,
  backupsLimit,
  loadBackups,
  loadMoreBackups,
  setBackupsPageLength,
} = useSite(props.siteName)

const pageLengths = [20, 50, 100].map((n) => ({ label: `${n} per page`, value: n }))

const backingUp = ref(false)
const error = ref('')

// Both of these were ref(null), which types the value as `null` and leaves
// every read of it a `never`. The config is a BackupSchedule.
const configRef = ref<InstanceType<typeof BackupConfigDialog> | null>(null)
const config = ref<BackupSchedule | null>(null)
const enabled = computed(() => !!config.value?.schedule)

const scheduleSummary = computed(() =>
  enabled.value && config.value?.schedule
    ? `${cronToLabel(config.value.schedule)}.`
    : 'Manual backups are kept until you delete them.',
)

const loadConfig = async () => {
  try {
    config.value = await sitesApi.backups.schedule.get(props.siteName)
  } catch {
    config.value = null
  }
}

const backupNow = async () => {
  backingUp.value = true
  error.value = ''
  try {
    const result = await sitesApi.backups.create(props.siteName)
    if (result.task_id) {
      toast.success('Backup started')
      // Refresh the list after a short delay to let the backup complete
      setTimeout(() => loadBackups(), 3000)
    } else {
      error.value = apiErrorMessage(result, 'Backup failed.')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Backup failed.'
  } finally {
    backingUp.value = false
  }
}

// Table.vue sizes columns with `class`, not a `width` prop - `width: 2` and
// friends were ListView's flex units and silently did nothing here.
const columns = [
  { label: 'Date', key: 'timestamp', class: 'w-1/3' },
  { label: 'Database', key: 'database', class: 'tabular-nums' },
  { label: 'Public', key: 'public', class: 'tabular-nums' },
  { label: 'Private', key: 'private', class: 'tabular-nums' },
  { label: 'Offsite', key: 'offsite', class: 'text-center' },
  { label: '', key: 'actions', class: 'w-12' },
]

type FileKind = BackupFile['kind']

const fileOf = (set: Backup, kind: FileKind): BackupFile | null =>
  set.files?.find((f) => f.kind === kind) ?? null
const fmtSize = (b?: number) =>
  !b ? '-' : b < 1024 ** 2 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1024 ** 2).toFixed(1)} MB`

const rows = computed(() =>
  backups.value.map((set) => ({
    name: set.created_at,
    timestamp: fmtDateTime(set.created_at),
    database: fmtSize(fileOf(set, 'database')?.size_bytes),
    public: fmtSize(fileOf(set, 'public-file')?.size_bytes),
    private: fmtSize(fileOf(set, 'private-file')?.size_bytes),
    set,
  })),
)

// The offsite metadata's file_type keys don't match the UI's kind names;
// this is the same mapping BackupReader uses to merge remote-only files in.
const OFFSITE_KIND_KEYS: Record<string, string> = {
  database: 'database',
  'public-file': 'files',
  'private-file': 'private_files',
  site_config: 'site_config',
}

const menuOptions = (set: Backup): DropdownItem[] => {
  const kinds: Array<[FileKind, string]> = [
    ['database', 'Download Database'],
    ['public-file', 'Download Public'],
    ['private-file', 'Download Private'],
    ['site_config', 'Download Config'],
  ]
  return [
    ...kinds
      .filter(([k]) => fileOf(set, k))
      .map(([k, label]) => ({
        label,
        icon: 'lucide-download',
        onClick: () => downloadFile(set, k),
      })),
    {
      label: 'Restore backup',
      icon: 'lucide-history',
      onClick: () => {
        restoreTarget.value = set
        restoreRef.value?.open()
      },
    },
    {
      label: 'Delete backup',
      icon: 'lucide-trash-2',
      theme: 'red',
      onClick: () => {
        deleteTarget.value = set
        showDelete.value = true
      },
    },
  ]
}

const restoreRef = ref<InstanceType<typeof RestoreDialog> | null>(null)
const restoreTarget = ref<Backup | null>(null)

const downloadViaAnchor = (url: string) => {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = ''
  anchor.target = '_blank'
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

const downloadFile = async (set: Backup, kind: FileKind) => {
  const file = fileOf(set, kind)
  if (file?.path) {
    downloadViaAnchor(sitesApi.backups.download(props.siteName, set.timestamp, file.filename))
    return
  }
  // Offsite-only file: fetch a direct, time-limited S3 link and open it -
  // this server never proxies or re-downloads the transfer.
  error.value = ''
  try {
    const links = await sitesApi.backups.downloadLinks(props.siteName, set.timestamp)
    if (hasApiError(links)) {
      error.value = apiErrorMessage(links, 'Could not load offsite backup.')
      return
    }
    const url = links[OFFSITE_KIND_KEYS[kind]]
    if (!url) {
      error.value = 'Backup file not found offsite.'
      return
    }
    downloadViaAnchor(url)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to get offsite download link.'
  }
}

const showDelete = ref(false)
const deleteTarget = ref<Backup | null>(null)
const deleting = ref(false)
const deleteError = ref('')

const confirmDelete = async () => {
  deleting.value = true
  deleteError.value = ''
  try {
    const filenames = (deleteTarget.value?.files ?? []).map((f) => f.filename)
    const data = await tasksApi.run('delete-backup', { site: props.siteName, filenames })
    if (data.task_id) {
      showDelete.value = false
      openTaskDetailPage(router, data.task_id)
    } else deleteError.value = apiErrorMessage(data, 'Delete failed.')
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : 'Delete failed.'
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  loadBackups()
  loadConfig()
})
</script>

<template>
  <div>
    <!-- Header row -->
    <div class="flex sm:flex-row flex-col sm:justify-between sm:items-center gap-3 mb-4">
      <div>
        <p class="font-medium text-ink-gray-8">Automated backups</p>
        <p class="mt-0.5 text-ink-gray-5 text-p-sm">{{ scheduleSummary }}</p>
      </div>
      <Button size="sm" variant="subtle" @click="configRef?.open()">
        <template #prefix><span class="size-4 lucide-settings" /></template>
        Configure
      </Button>
    </div>

    <!-- Error -->
    <ErrorMessage v-if="error" :message="error" class="mb-4" />

    <!-- Backup list -->
    <div :class="backups.length ? '' : 'rounded-7 border border-dashed border-outline-gray-2'">
      <div v-if="backupsLoading" class="flex justify-center py-12">
        <LoadingText />
      </div>

      <EmptyState
        v-else-if="!backups.length"
        :bordered="false"
        icon="lucide-archive"
        title="No backups yet"
        :description="
          enabled
            ? 'Automatic backups run on schedule. You can also back up now.'
            : 'Enable automatic backups to start protecting your site.'
        "
      >
        <Button size="sm" :loading="backingUp" @click="backupNow">
          <template #prefix><span class="size-4 lucide-archive" /></template>
          Back up now
        </Button>
      </EmptyState>

      <Table v-else :columns="columns" :rows="rows" height="max-h-[32rem]">
        <template #offsite="{ row }">
          <div class="flex justify-center">
            <span
              v-if="row.set.is_offsite"
              class="size-4 text-ink-gray-6 lucide-check"
              title="Backed up offsite"
            />
            <span v-else class="size-4 text-ink-gray-4 lucide-x" title="Not backed up offsite" />
          </div>
        </template>

        <template #actions="{ row }">
          <div class="flex justify-end">
            <Dropdown :options="menuOptions(row.set)">
              <template #default="{ open }">
                <Button
                  variant="ghost"
                  :active="open"
                  icon="lucide-ellipsis"
                  label="Backup actions"
                  tooltip="Actions"
                />
              </template>
            </Dropdown>
          </div>
        </template>
      </Table>

      <div v-if="backupsHasMore || backups.length > 20" class="flex items-center gap-3 mt-2 px-1">
        <Select
          size="sm"
          :model-value="backupsLimit"
          :options="pageLengths"
          @update:model-value="(value) => setBackupsPageLength(Number(value))"
        />

        <span class="text-ink-gray-5 text-sm">{{ backups.length }} backups</span>

        <Button v-if="backupsHasMore" class="ml-auto" @click="loadMoreBackups">Load more</Button>
      </div>
    </div>

    <!-- Delete confirmation dialog -->
    <Dialog v-model="showDelete" title="Delete backup" size="sm">
      <p class="text-ink-gray-6 text-p-sm">
        Are you sure you want to delete this backup? This action cannot be undone.
      </p>
      <ErrorMessage v-if="deleteError" :message="deleteError" class="mt-3" />
      <template #actions>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" @click="showDelete = false">Cancel</Button>
          <Button variant="solid" theme="red" :loading="deleting" @click="confirmDelete">
            Delete
          </Button>
        </div>
      </template>
    </Dialog>

    <!-- Dialogs (rendered as portals, no layout impact) -->
    <BackupConfigDialog ref="configRef" :site-name="siteName" @saved="loadConfig" />
    <RestoreDialog ref="restoreRef" :site-name="siteName" :backup="restoreTarget" />
  </div>
</template>
