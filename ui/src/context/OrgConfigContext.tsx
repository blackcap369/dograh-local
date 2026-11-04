'use client';

import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { client } from '@/client/client.gen';
import { createOrganizationApiV1OrganizationsPost,getCurrentOrganizationContextApiV1OrganizationsContextGet, getMyOrganizationsApiV1OrganizationsMineGet, getPreferencesApiV1OrganizationsPreferencesGet, getUserConfigurationsApiV1UserConfigurationsUserGet, switchOrganizationApiV1OrganizationsSwitchPost } from '@/client/sdk.gen';
import type { OrganizationContextResponse, OrganizationListItem, OrganizationPreferences, UserConfigurationRequestResponseSchema } from '@/client/types.gen';
import { setupAuthInterceptor } from '@/lib/apiClient';
import { detailFromError } from '@/lib/apiError';
import type { AuthUser } from '@/lib/auth';
import { useAuth } from '@/lib/auth';

interface TeamPermission {
    id: string;
}

interface OrganizationPricing {
    price_per_second_usd: number | null;
    currency: string;
    billing_enabled: boolean;
}

interface OrgConfigContextType {
    orgContext: OrganizationContextResponse | null;
    userConfig: UserConfigurationRequestResponseSchema | null;
    loading: boolean;
    error: Error | null;
    refreshConfig: () => Promise<void>;
    permissions: TeamPermission[];
    user: AuthUser | null;
    organizationPricing: OrganizationPricing | null;
    organizationPreferences: OrganizationPreferences | null;
    externalPbxIntegrationsEnabled: boolean;
    organizations: OrganizationListItem[];
    switchOrganization: (id: number) => Promise<void>;
    createOrganization: (name: string) => Promise<OrganizationListItem>;
}

const OrgConfigContext = createContext<OrgConfigContextType | null>(null);

const pricingFromUserConfig = (
    userConfig: UserConfigurationRequestResponseSchema,
): OrganizationPricing | null => {
    if (!userConfig.organization_pricing) {
        return null;
    }

    return {
        price_per_second_usd: userConfig.organization_pricing.price_per_second_usd as number | null,
        currency: (userConfig.organization_pricing.currency as string) || 'USD',
        billing_enabled: (userConfig.organization_pricing.billing_enabled as boolean) || false,
    };
};

export function OrgConfigProvider({ children }: { children: ReactNode }) {
    const [orgContext, setOrgContext] = useState<OrganizationContextResponse | null>(null);
    const [userConfig, setUserConfig] = useState<UserConfigurationRequestResponseSchema | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);
    const [organizationPricing, setOrganizationPricing] = useState<OrganizationPricing | null>(null);
    const [organizationPreferences, setOrganizationPreferences] = useState<OrganizationPreferences | null>(null);
    const [permissions, setPermissions] = useState<TeamPermission[]>([]);
    const [organizations, setOrganizations] = useState<OrganizationListItem[]>([]);

    const auth = useAuth();

    const authRef = useRef(auth);
    authRef.current = auth;

    const hasFetchedConfig = useRef(false);
    const hasFetchedPermissions = useRef(false);

    if (!auth.loading && auth.isAuthenticated) {
        setupAuthInterceptor(client, auth.getAccessToken);
    }

    useEffect(() => {
        if (auth.loading || hasFetchedPermissions.current) {
            return;
        }
        hasFetchedPermissions.current = true;

        const fetchPermissions = async () => {
            const currentAuth = authRef.current;
            if (currentAuth.provider === 'stack' && currentAuth.getSelectedTeam && currentAuth.listPermissions) {
                const selectedTeam = currentAuth.getSelectedTeam();
                if (selectedTeam) {
                    try {
                        const perms = await currentAuth.listPermissions(selectedTeam);
                        setPermissions(Array.isArray(perms) ? perms : []);
                    } catch {
                        setPermissions([]);
                    }
                } else {
                    setPermissions([]);
                }
            } else {
                setPermissions([{ id: 'admin' }]);
            }
        };

        fetchPermissions();
    }, [auth.loading, auth.provider]);

    const fetchConfig = useCallback(async () => {
        const currentAuth = authRef.current;
        if (!currentAuth.isAuthenticated) {
            return;
        }

        setLoading(true);
        try {
            const [orgContextResponse, userConfigResponse, preferencesResponse, orgsResponse] = await Promise.all([
                getCurrentOrganizationContextApiV1OrganizationsContextGet(),
                getUserConfigurationsApiV1UserConfigurationsUserGet(),
                getPreferencesApiV1OrganizationsPreferencesGet(),
                getMyOrganizationsApiV1OrganizationsMineGet(),
            ]);

            if (preferencesResponse.error) {
                throw new Error(detailFromError(preferencesResponse.error, 'Failed to load organization preferences'));
            }

            if (orgContextResponse.data) {
                setOrgContext(orgContextResponse.data);
            }

            if (userConfigResponse.data) {
                setUserConfig(userConfigResponse.data);
                setOrganizationPricing(pricingFromUserConfig(userConfigResponse.data));
            }

            if (orgsResponse.data) {
                setOrganizations(Array.isArray(orgsResponse.data) ? orgsResponse.data : []);
            }

            if (preferencesResponse.data) {
                setOrganizationPreferences(preferencesResponse.data);
            }

            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err : new Error('Failed to fetch organization configuration'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (auth.loading || !auth.isAuthenticated || hasFetchedConfig.current) {
            return;
        }
        hasFetchedConfig.current = true;
        fetchConfig();
    }, [auth.loading, auth.isAuthenticated, fetchConfig]);

    const switchOrganization = useCallback(async (id: number) => {
        const response = await switchOrganizationApiV1OrganizationsSwitchPost({
            body: { organization_id: id },
        });

        if (response.error) {
            throw new Error(detailFromError(response.error, 'Failed to switch organization'));
        }

        // The backend persisted the new selection on `users.selected_organization_id`,
        // so every later request is already scoped to the new org. Refresh the rest
        // of the org-derived config (pricing, preferences, user configuration) and
        // take the returned context directly rather than re-fetching it.
        if (response.data) {
            setOrgContext(response.data);
        }
        await fetchConfig();
    }, [fetchConfig]);

    const createOrganization = useCallback(async (name: string) => {
        const response = await createOrganizationApiV1OrganizationsPost({
            body: { name },
        });

        if (response.error || !response.data) {
            throw new Error(detailFromError(response.error, 'Failed to create organization'));
        }

        // Refresh rather than appending locally: the switcher reads its options from
        // `organizations`, and a stale list here is what makes a freshly created
        // business look like the create silently did nothing.
        await fetchConfig();

        return response.data;
    }, [fetchConfig]);

    const refreshConfig = useCallback(async () => {
        await fetchConfig();
    }, [fetchConfig]);    return (
        <OrgConfigContext.Provider
            value={{
                orgContext,
                userConfig,
                loading,
                error,
                refreshConfig,
                permissions,
                user: auth.user,
                organizationPricing,
                organizationPreferences,
                externalPbxIntegrationsEnabled:
                    organizationPreferences?.external_pbx_integrations_enabled ?? false,
                organizations,
                switchOrganization,
                createOrganization,
            }}
        >
            {children}
        </OrgConfigContext.Provider>
    );
}

export function useOrgConfig() {
    const context = useContext(OrgConfigContext);
    if (!context) {
        throw new Error('useOrgConfig must be used within an OrgConfigProvider');
    }
    return context;
}
