"use client";

import { ExternalLink, KeyRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get,
    getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet,
    saveModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Put,
} from "@/client/sdk.gen";
import { createProviderKeyApiV1OrganizationsProviderKeysPost, deleteProviderKeyApiV1OrganizationsProviderKeysKeyIdDelete, listProviderKeysApiV1OrganizationsProviderKeysGet } from "@/client/sdk.gen";
import type {
    ModelConfigurationPricingResponse,
    OrganizationAiModelConfigurationResponse,
    OrganizationAiModelConfigurationV2,
} from "@/client/types.gen";
import type { ProviderKeyResponse } from "@/client/types.gen";
import { AIModelConfigurationV2Editor, type ModelConfigurationDefaultsV2 } from "@/components/AIModelConfigurationV2Editor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useUserConfig } from "@/context/UserConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { fetchModelConfigurationPricing } from "@/lib/modelConfigurationPricing";

export default function ModelConfigurationV2({ docsUrl }: { docsUrl?: string }) {
    const auth = useAuth();
    const { refreshConfig } = useUserConfig();
    const hasFetched = useRef(false);

    const [defaults, setDefaults] = useState<ModelConfigurationDefaultsV2 | null>(null);
    const [response, setResponse] = useState<OrganizationAiModelConfigurationResponse | null>(null);
    const [pricing, setPricing] = useState<ModelConfigurationPricingResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    // Saved-key vault (V2.5): manage the organization's stored API keys.
    const [vaultOpen, setVaultOpen] = useState(false);
    const [savedKeys, setSavedKeys] = useState<ProviderKeyResponse[]>([]);
    const [newKeyService, setNewKeyService] = useState("llm");
    const [newKeyProvider, setNewKeyProvider] = useState("");
    const [newKeyAlias, setNewKeyAlias] = useState("");
    const [newKeyValue, setNewKeyValue] = useState("");
    const [isSavingKey, setIsSavingKey] = useState(false);

    // Provider options come from the same backend defaults the configuration
    // form uses, filtered by the chosen service — no free-typed provider
    // names, so a typo can never attach a key to a provider that does not
    // exist.
    const vaultProviderOptions: string[] =
        newKeyService === "realtime"
            ? Object.keys(defaults?.byok.realtime.realtime ?? {})
            : Object.keys(
                  (defaults?.byok.pipeline as unknown as Record<
                      string,
                      Record<string, unknown>
                  > | undefined)?.[newKeyService] ?? {}
              ).filter((p) => p !== "default_providers");

    useEffect(() => {
        if (auth.loading || !auth.user || hasFetched.current) return;
        hasFetched.current = true;

        const load = async () => {
            setLoading(true);
            setError(null);
            const [defaultsResult, configResult, pricingResult] = await Promise.all([
                getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet(),
                getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get(),
                fetchModelConfigurationPricing(),
            ]);

            if (defaultsResult.error) {
                setError(detailFromError(defaultsResult.error, "Failed to load model configuration defaults"));
                setLoading(false);
                return;
            }
            if (configResult.error) {
                setError(detailFromError(configResult.error, "Failed to load model configuration"));
                setLoading(false);
                return;
            }

            const nextDefaults = defaultsResult.data as ModelConfigurationDefaultsV2;
            if (!nextDefaults || !configResult.data) {
                setError("Failed to load model configuration");
                setLoading(false);
                return;
            }
            setDefaults(nextDefaults);
            setResponse(configResult.data);
            setPricing(pricingResult);
            setLoading(false);
        };

        load();

    }, [auth.loading, auth.user]);

    const saveConfiguration = async (configuration: OrganizationAiModelConfigurationV2) => {
        if (!defaults) return;
        setError(null);
        setNotice(null);

        const result = await saveModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Put({
            body: configuration,
        });

        if (result.error) {
            throw new Error(detailFromError(result.error, "Failed to save model configuration"));
        }
        if (!result.data) {
            throw new Error("Failed to save model configuration");
        }

        setResponse(result.data);
        void fetchModelConfigurationPricing().then(setPricing);
        await refreshConfig();
        setNotice("Model configuration saved");
    };

    if (loading) {
        return (
            <div className="w-full max-w-4xl mx-auto space-y-6">
                <Skeleton className="h-10 w-80" />
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-96 w-full" />
            </div>
        );
    }

    const loadVault = async () => {
        const response = await listProviderKeysApiV1OrganizationsProviderKeysGet();
        if (!response.error) setSavedKeys(response.data ?? []);
    };

    const openVault = async () => {
        setVaultOpen(true);
        await loadVault();
    };

    const handleSaveKey = async () => {
        if (!newKeyProvider.trim() || !newKeyAlias.trim() || !newKeyValue.trim()) {
            toast.error("Provider, alias, and API key are all required");
            return;
        }
        try {
            setIsSavingKey(true);
            const response = await createProviderKeyApiV1OrganizationsProviderKeysPost({
                body: {
                    service: newKeyService,
                    provider: newKeyProvider.trim(),
                    alias: newKeyAlias.trim(),
                    api_key: newKeyValue,
                },
            });
            if (response.error || !response.data) {
                throw new Error(detailFromError(response.error, "Could not save the key"));
            }
            toast.success(`Saved "${response.data.alias}"`);
            setNewKeyProvider("");
            setNewKeyAlias("");
            setNewKeyValue("");
            await loadVault();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not save the key");
        } finally {
            setIsSavingKey(false);
        }
    };

    const handleDeleteKey = async (key: ProviderKeyResponse) => {
        const response = await deleteProviderKeyApiV1OrganizationsProviderKeysKeyIdDelete({
            path: { key_id: key.id },
        });
        if (response.error) {
            toast.error(detailFromError(response.error, "Could not delete the key"));
            return;
        }
        toast.success(`Deleted "${key.alias}"`);
        await loadVault();
    };

    return (
        <div className="w-full max-w-4xl mx-auto space-y-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                    <h1 className="text-3xl font-bold">AI Models Configuration</h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        Organization-scoped model settings.{" "}
                        {docsUrl && (
                            <a href={docsUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 underline">
                                Learn more <ExternalLink className="h-3 w-3" />
                            </a>
                        )}
                    </p>
                </div>
                <Button variant="outline" onClick={() => void openVault()}>
                    <KeyRound className="mr-2 h-4 w-4" /> Saved keys
                </Button>
            </div>

            {error && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                </div>
            )}
            {notice && (
                <div className="rounded-md border border-green-500/40 bg-green-500/10 px-4 py-3 text-sm text-green-700 dark:text-green-300">
                    {notice}
                </div>
            )}

            {defaults && response && (
                <AIModelConfigurationV2Editor
                    defaults={defaults}
                    configuration={response.configuration}
                    effectiveConfiguration={response.effective_configuration}
                    pricing={pricing}
                    onSave={saveConfiguration}
                />
             )}

            <Dialog open={vaultOpen} onOpenChange={setVaultOpen}>
                <DialogContent className="max-h-[85vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Saved API keys</DialogTitle>
                        <DialogDescription>
                            Keys stored encrypted for this organization. In any
                            model configuration, pick a saved key from the
                            &ldquo;Use a saved key&rdquo; dropdown instead of
                            retyping it. Saved keys are never shown again after
                            saving.
                        </DialogDescription>
                    </DialogHeader>

                    <div className="grid gap-3 rounded-lg border border-border/60 p-4">
                        <div className="grid gap-2">
                            <Label htmlFor="vault-service">Service</Label>
                            <Select
                            value={newKeyService}
                            onValueChange={(value) => {
                                setNewKeyService(value);
                                setNewKeyProvider("");
                            }}
                        >
                                <SelectTrigger id="vault-service">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {["llm", "tts", "stt", "embeddings", "realtime"].map((s) => (
                                        <SelectItem key={s} value={s}>
                                            {s.toUpperCase()}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="grid gap-2">
                            <Label htmlFor="vault-provider">Provider</Label>
                            <Select
                                value={newKeyProvider}
                                onValueChange={setNewKeyProvider}
                            >
                                <SelectTrigger id="vault-provider">
                                    <SelectValue placeholder="Select the provider" />
                                </SelectTrigger>
                                <SelectContent>
                                    {vaultProviderOptions.map((provider) => (
                                        <SelectItem key={provider} value={provider}>
                                            {provider}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="grid gap-2">
                            <Label htmlFor="vault-alias">Alias</Label>
                            <Input
                                id="vault-alias"
                                value={newKeyAlias}
                                onChange={(e) => setNewKeyAlias(e.target.value)}
                                placeholder='e.g. "Acme OpenAI"'
                            />
                        </div>
                        <div className="grid gap-2">
                            <Label htmlFor="vault-key">API key</Label>
                            <Input
                                id="vault-key"
                                type="password"
                                value={newKeyValue}
                                onChange={(e) => setNewKeyValue(e.target.value)}
                                placeholder="Paste the API key"
                            />
                        </div>
                        <Button onClick={handleSaveKey} disabled={isSavingKey} className="w-full">
                            {isSavingKey ? "Saving..." : "Save key"}
                        </Button>
                    </div>

                    <div className="space-y-2">
                        <p className="text-sm font-medium">Saved keys</p>
                        {savedKeys.length === 0 ? (
                            <p className="text-sm text-muted-foreground">No keys saved yet.</p>
                        ) : (
                            <ul className="divide-y divide-border/60 rounded-lg border border-border/60">
                                {savedKeys.map((key) => (
                                    <li key={key.id} className="flex items-center justify-between gap-3 px-3 py-2">
                                        <div className="min-w-0">
                                            <p className="truncate text-sm font-medium">
                                                {key.alias}{" "}
                                                <Badge variant="secondary" className="uppercase">
                                                    {key.service}
                                                </Badge>{" "}
                                                <span className="text-muted-foreground">{key.provider}</span>
                                            </p>
                                            <p className="font-mono text-xs text-muted-foreground">{key.masked_key}</p>
                                        </div>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => void handleDeleteKey(key)}
                                        >
                                            Delete
                                        </Button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setVaultOpen(false)}>
                            Close
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
