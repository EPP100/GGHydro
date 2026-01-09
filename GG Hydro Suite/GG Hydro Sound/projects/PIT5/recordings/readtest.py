from nptdms import TdmsFile


def print_tdms_metadata(filepath):
    with TdmsFile.read_metadata(filepath) as tdms_file:

        print("\nVerified File Properties:")
        print(tdms_file.properties)
        print(tdms_file)

        print(f"--- FILE PROPERTIES: {filepath} ---")
        for prop, val in tdms_file.properties.items():
            print(f"  [File] {prop}: {val}")

        for group in tdms_file.groups():
            print(f"\n--- GROUP: {group.name} ---")
            for prop, val in group.properties.items():
                print(f"  [Group] {prop}: {val}")

            for channel in group.channels():
                if channel.properties:
                    print(f"    -> Channel: {channel.name}")
                    for prop, val in channel.properties.items():
                        print(f"       [Chan] {prop}: {val}")


# Usage
print_tdms_metadata(
    "C:\\Users\\Gabriel\\Documents\\GG Hydro Suite\\GG Hydro Sound\\projects\\PIT5\\recordings\\2025-12-29 - PIT5 - U1 - 1436 - 1346.tdms"
)
