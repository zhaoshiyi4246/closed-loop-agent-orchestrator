package codexsecurity

import "testing"

func TestWindowsVaultACLPolicyRejectsUntrustedCredentialAccess(t *testing.T) {
	write := codexWindowsWriteData | codexWindowsWriteDAC
	tests := []struct {
		name         string
		ownerTrusted bool
		aces         []codexWindowsACE
		want         bool
	}{
		{name: "untrusted file reader", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: true, PrincipalTrusted: false, Mask: codexWindowsReadData}}},
		{name: "untrusted generic reader", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: true, PrincipalTrusted: false, Mask: codexWindowsGenericRead}}},
		{name: "untrusted writer", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: true, PrincipalTrusted: false, Mask: codexWindowsWriteData}}},
		{name: "untrusted ACL editor", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: true, PrincipalTrusted: false, Mask: codexWindowsWriteDAC}}},
		{name: "trusted system writer", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: true, PrincipalTrusted: true, Mask: write}}, want: true},
		{name: "trusted system reader", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: true, PrincipalTrusted: true, Mask: codexWindowsGenericRead}}, want: true},
		{name: "deny does not grant rights", ownerTrusted: true, aces: []codexWindowsACE{{Allowed: false, PrincipalTrusted: false, Mask: write}}, want: true},
		{name: "untrusted owner", ownerTrusted: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := codexWindowsVaultACLIsSafe(tt.ownerTrusted, tt.aces); got != tt.want {
				t.Fatalf("ACL safety = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestWindowsAncestorACLPolicyAllowsReadButRejectsMutation(t *testing.T) {
	if !codexWindowsAncestorACLIsSafe(true, []codexWindowsACE{{Allowed: true, PrincipalTrusted: false, Mask: codexWindowsGenericRead}}) {
		t.Fatal("read-only ancestor ACL rejected")
	}
	if codexWindowsAncestorACLIsSafe(true, []codexWindowsACE{{Allowed: true, PrincipalTrusted: false, Mask: codexWindowsDeleteChild}}) {
		t.Fatal("mutable ancestor ACL accepted")
	}
}

func TestWindowsVolumeRootPolicyOnlyAllowsDirectoryCreation(t *testing.T) {
	create := codexWindowsACE{Allowed: true, Mask: codexWindowsAppendData, RootDirectoryCreateOnly: true}
	if !codexWindowsAncestorACLPolicy(true, []codexWindowsACE{create}, true) {
		t.Fatal("verified root sibling-directory creation rejected")
	}
	if codexWindowsAncestorACLPolicy(false, []codexWindowsACE{create}, true) ||
		codexWindowsAncestorACLPolicy(true, []codexWindowsACE{create}, false) ||
		codexWindowsVaultACLIsSafe(true, []codexWindowsACE{create}) {
		t.Fatal("root exception admitted an untrusted owner, normal ancestor or vault")
	}
	for name, mask := range map[string]uint32{
		"create file or set reparse": codexWindowsWriteData,
		"write attributes":           codexWindowsWriteAttributes, "write EA": codexWindowsWriteEA,
		"delete child": codexWindowsDeleteChild, "delete": codexWindowsDelete,
		"write DAC": codexWindowsWriteDAC, "write owner": codexWindowsWriteOwner,
		"generic all": codexWindowsGenericAll, "generic write": codexWindowsGenericWrite,
	} {
		t.Run(name, func(t *testing.T) {
			ace := create
			ace.Mask |= mask
			if codexWindowsAncestorACLPolicy(true, []codexWindowsACE{ace}, true) {
				t.Fatalf("root creation exempted dangerous rights %#x", ace.Mask)
			}
		})
	}
	for _, ace := range []codexWindowsACE{
		{Allowed: true, Mask: codexWindowsAppendData}, // nonstandard or different principal
		{Allowed: true, Mask: codexWindowsAppendData, RootDirectoryCreateOnly: true, Unsupported: true},
		{Unsupported: true}, // Unknown/object/callback ACEs fail closed, even with zero mask.
	} {
		if codexWindowsAncestorACLPolicy(true, []codexWindowsACE{ace}, true) {
			t.Fatal("unsupported root ACE accepted", ace)
		}
	}
}

func TestWindowsOwnerRightsFollowOnlyAnAlreadyTrustedOwner(t *testing.T) {
	ownerACE := codexWindowsACE{Allowed: true, OwnerRights: true, Mask: codexWindowsGenericAll}
	if !codexWindowsVaultACLIsSafe(true, []codexWindowsACE{ownerACE}) ||
		!codexWindowsAncestorACLIsSafe(true, []codexWindowsACE{ownerACE}) {
		t.Fatal("owner rights did not resolve to the already trusted owner")
	}
	if codexWindowsVaultACLIsSafe(false, []codexWindowsACE{ownerACE}) ||
		codexWindowsAncestorACLIsSafe(false, []codexWindowsACE{ownerACE}) {
		t.Fatal("owner rights made an untrusted owner safe")
	}
	// Other creator/unknown principals are never marked OwnerRights.
	ownerACE.OwnerRights = false
	if codexWindowsVaultACLIsSafe(true, []codexWindowsACE{ownerACE}) ||
		codexWindowsAncestorACLIsSafe(true, []codexWindowsACE{ownerACE}) {
		t.Fatal("unrelated principal inherited the owner's trust")
	}
}

func TestWindowsNoFollowAndWriteThroughPolicies(t *testing.T) {
	if got := codexWindowsNoFollowOpenFlags(); got&codexWindowsOpenReparsePoint == 0 || got&codexWindowsBackupSemantics == 0 {
		t.Fatalf("no-follow open flags = %#x", got)
	}
	if got := codexWindowsAtomicReplaceFlags(); got != codexWindowsMoveReplaceExisting|codexWindowsMoveWriteThrough {
		t.Fatalf("atomic replace flags = %#x", got)
	}
	if got := codexWindowsDirectoryFlushAccess(); got&codexWindowsGenericWrite == 0 || got&codexWindowsReadControl == 0 {
		t.Fatalf("directory flush access = %#x", got)
	}
}

func TestWindowsPathMetadataPolicyRejectsReparseOwnerACLTypeAndHardLinks(t *testing.T) {
	safeFile := codexWindowsPathMetadata{OwnerTrusted: true, ACLSafe: true, HardLinks: 1, VolumeSerial: 9, FileIndexHigh: 4, FileIndexLow: 2}
	if !codexWindowsPathMetadataIsSafe(safeFile, false, true) {
		t.Fatal("safe file metadata rejected")
	}
	for name, mutate := range map[string]func(*codexWindowsPathMetadata){
		"reparse":   func(m *codexWindowsPathMetadata) { m.Attributes |= codexWindowsAttributeReparsePoint },
		"directory": func(m *codexWindowsPathMetadata) { m.Attributes |= codexWindowsAttributeDirectory },
		"hardlink":  func(m *codexWindowsPathMetadata) { m.HardLinks = 2 },
		"owner":     func(m *codexWindowsPathMetadata) { m.OwnerTrusted = false },
		"acl":       func(m *codexWindowsPathMetadata) { m.ACLSafe = false },
	} {
		t.Run(name, func(t *testing.T) {
			metadata := safeFile
			mutate(&metadata)
			if codexWindowsPathMetadataIsSafe(metadata, false, true) {
				t.Fatalf("unsafe %s metadata accepted", name)
			}
		})
	}
	safeDirectory := safeFile
	safeDirectory.Attributes = codexWindowsAttributeDirectory
	if !codexWindowsPathMetadataIsSafe(safeDirectory, true, false) {
		t.Fatal("safe ancestor directory rejected")
	}
	changed := safeFile
	changed.FileIndexLow++
	if codexWindowsSameStableIdentity(safeFile, changed) {
		t.Fatal("changed Windows file identity accepted")
	}
	if !codexWindowsSameStableIdentity(safeFile, safeFile) {
		t.Fatal("stable Windows file identity rejected")
	}
}
